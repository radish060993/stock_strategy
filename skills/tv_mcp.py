"""TradingView MCP 客戶端（Streamable HTTP + OAuth 2.1 Bearer）。

伺服器：https://mcp.tradingview.com/mcp
授權：  由 skills.tv_auth 取得 access token（scope: mcp:read mcp:tools）

只實作盯盤需要的最小子集：initialize / tools/list / tools/call。
伺服器目前為無狀態（不回傳 Mcp-Session-Id），但本模組仍會沿用它回傳的 session id。

用法
    python -m skills.tv_mcp tools                       # 列出可用工具
    python -m skills.tv_mcp watchlists                  # 列出我的 watchlist
    python -m skills.tv_mcp call <tool> '<json args>'   # 呼叫任意工具
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import time
from typing import Any

import requests

from . import tv_auth

log = logging.getLogger(__name__)

MCP_URL = "https://mcp.tradingview.com/mcp"
PROTOCOL_VERSION = "2025-06-18"
CLIENT_INFO = {"name": "stock-strategy-agent", "version": "1.0"}
MAX_RETRIES = 4
BACKOFF_BASE = 5.0  # 秒；TradingView scanner 對頻繁呼叫會回 429


class TVMCPError(Exception):
    pass


class TVMCPRateLimited(TVMCPError):
    pass


def _parse_response(resp: requests.Response) -> dict:
    """支援 application/json 與 text/event-stream 兩種回應。"""
    ctype = resp.headers.get("Content-Type", "")
    if "text/event-stream" in ctype:
        for line in resp.text.splitlines():
            if line.startswith("data:"):
                payload = line[5:].strip()
                if payload:
                    return json.loads(payload)
        raise TVMCPError("SSE 回應中沒有 data 事件")
    try:
        return resp.json()
    except ValueError as exc:
        raise TVMCPError(f"回應非 JSON: {resp.text[:200]}") from exc


class TVMCPClient:
    def __init__(self, access_token: str | None = None, timeout: float = 60.0,
                 interactive: bool = False, max_retries: int = MAX_RETRIES):
        token = access_token or tv_auth.get_access_token(interactive=interactive)
        if not token:
            raise TVMCPError("尚未授權，請先執行：python -m skills.tv_auth login")
        self.timeout = timeout
        self.max_retries = max_retries
        self.session_id: str | None = None
        self._id = 0
        self._watchlists_cache: list[dict] | None = None
        self._http = requests.Session()
        self._http.headers.update({
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": PROTOCOL_VERSION,
        })
        self._initialized = False

    # -- JSON-RPC ----------------------------------------------------------
    def _post(self, payload: dict) -> requests.Response:
        headers = {"Mcp-Session-Id": self.session_id} if self.session_id else {}
        try:
            return self._http.post(MCP_URL, json=payload, headers=headers, timeout=self.timeout)
        except requests.RequestException as exc:
            raise TVMCPError(f"MCP 連線失敗: {exc}") from exc

    def _request(self, method: str, params: dict | None = None) -> Any:
        self._id += 1
        resp = self._post({"jsonrpc": "2.0", "id": self._id, "method": method,
                           "params": params or {}})
        if resp.status_code == 401:
            raise TVMCPError("授權失效（401），請重新執行：python -m skills.tv_auth login")
        if resp.status_code == 429:
            raise TVMCPRateLimited(f"MCP 限流（429）: {resp.text[:120]}")
        if resp.status_code != 200:
            raise TVMCPError(f"MCP HTTP {resp.status_code}: {resp.text[:200]}")
        if sid := resp.headers.get("Mcp-Session-Id"):
            self.session_id = sid
        data = _parse_response(resp)
        if "error" in data:
            err = data["error"]
            raise TVMCPError(f"MCP 錯誤 {err.get('code')}: {err.get('message')}")
        return data.get("result", {})

    def _notify(self, method: str, params: dict | None = None) -> None:
        try:
            self._post({"jsonrpc": "2.0", "method": method, "params": params or {}})
        except TVMCPError:
            log.debug("通知 %s 失敗（可忽略）", method)

    # -- MCP ---------------------------------------------------------------
    def initialize(self) -> dict:
        if self._initialized:
            return {}
        result = self._request("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": CLIENT_INFO,
        })
        self._notify("notifications/initialized")
        self._initialized = True
        return result

    def list_tools(self) -> list[dict]:
        self.initialize()
        return self._request("tools/list").get("tools", [])

    def call_tool(self, name: str, arguments: dict | None = None) -> Any:
        """呼叫工具並回傳解析後的結果；遇到 429 會自動退避重試。"""
        last_error: TVMCPError | None = None
        for attempt in range(self.max_retries):
            try:
                return self._call_tool_once(name, arguments)
            except TVMCPRateLimited as exc:
                last_error = exc
                if attempt == self.max_retries - 1:
                    break
                wait = BACKOFF_BASE * (2 ** attempt)
                log.warning("[%s] 被限流，%.0f 秒後重試（%d/%d）",
                            name, wait, attempt + 1, self.max_retries - 1)
                time.sleep(wait)
        raise last_error  # type: ignore[misc]

    def _call_tool_once(self, name: str, arguments: dict | None = None) -> Any:
        self.initialize()
        result = self._request("tools/call", {"name": name, "arguments": arguments or {}})

        if structured := result.get("structuredContent"):
            payload = structured
        else:
            texts = [c.get("text", "") for c in result.get("content", []) if c.get("type") == "text"]
            joined = "\n".join(texts)
            try:
                payload = json.loads(joined)
            except (json.JSONDecodeError, TypeError):
                payload = joined

        error_text = ""
        if result.get("isError"):
            error_text = str(payload)
        elif isinstance(payload, dict) and payload.get("success") is False:
            error_text = str(payload.get("error", payload))

        if error_text:
            # TradingView 會把上游 scanner 的 429 包在工具結果中回傳
            if ": 429" in error_text or "429:" in error_text:
                raise TVMCPRateLimited(f"{name}: {error_text[:160]}")
            raise TVMCPError(f"{name}: {error_text[:300]}")
        return payload

    # -- 常用包裝 -----------------------------------------------------------
    def list_watchlists(self) -> list[dict]:
        result = self.call_tool("mcp-watchlist-list-watchlists")
        watchlists = result.get("watchlists") if isinstance(result, dict) else None
        if not isinstance(watchlists, list):
            raise TVMCPError("TradingView watchlist 清單回應格式錯誤")
        self._watchlists_cache = watchlists
        return watchlists

    def get_watchlist(self, watchlist_id: str | int) -> dict:
        data = self.call_tool("mcp-watchlist-get-watchlist", {"watchlist_id": str(watchlist_id)})
        return data.get("watchlist", data)

    def get_active_watchlist(self) -> dict:
        data = self.call_tool("mcp-watchlist-get-active-watchlist")
        return data.get("watchlist", data)

    def _resolve_watchlist_symbol(self, symbol: str, market: str) -> str:
        normalized_market = market.upper()
        normalized_symbol = symbol.upper()
        if normalized_market == "TW":
            match = re.fullmatch(r"(\d+)\.(TW|TWO)", normalized_symbol)
            if not match:
                raise TVMCPError(f"無法辨識台股代號格式：{symbol}")
            exchange = "TWSE" if match.group(2) == "TW" else "TPEX"
            return f"{exchange}:{match.group(1)}"
        if normalized_market != "US":
            raise TVMCPError(f"不支援的市場：{market}")

        response = self.call_tool("mcp-tv-search-symbols", {
            "query": normalized_symbol,
            "type_filter": "stock",
        })
        data = response.get("data") if isinstance(response, dict) else None
        candidates = data.get("symbols") if isinstance(data, dict) else None
        if not isinstance(candidates, list):
            raise TVMCPError(f"TradingView 無法搜尋美股代號：{symbol}")

        preferred_exchanges = (
            "NASDAQ", "NYSE", "NYSEARCA", "NYSE ARCA", "AMEX",
            "NYSEAMERICAN", "ARCA", "CBOE", "BATS",
        )
        matching = [
            candidate for candidate in candidates
            if isinstance(candidate, dict)
            # ADR（如 GMAB、TSM）在 TradingView 的 type 為 "dr"
            and candidate.get("type") in ("stock", "dr")
            and candidate.get("currency_logoid") == "country/US"
            and str(candidate.get("symbol", "")).rsplit(":", 1)[-1].upper() == normalized_symbol
            and candidate.get("exchange") in preferred_exchanges
            and str(candidate.get("symbol", "")).split(":", 1)[0].upper().replace(" ", "")
            == str(candidate.get("exchange", "")).upper().replace(" ", "")
        ]
        if not matching:
            raise TVMCPError(f"TradingView 找不到有效美股交易所的代號：{symbol}")

        if normalized_symbol == "TSM":
            nyse_listing = next(
                (candidate for candidate in matching if candidate.get("exchange") == "NYSE"),
                None,
            )
            if nyse_listing is None:
                raise TVMCPError("TradingView 找不到 TSM 的 NYSE 掛牌")
            return str(nyse_listing["symbol"])

        matching.sort(key=lambda candidate: preferred_exchanges.index(candidate["exchange"]))
        return str(matching[0]["symbol"])

    def add_symbol_to_watchlist(self, watchlist_name: str, symbol: str, market: str) -> bool:
        """加入指定市場的 watchlist；若已存在則回傳 False，否則回傳 True。"""
        watchlists = self._watchlists_cache
        if watchlists is None:
            watchlists = self.list_watchlists()
        matches = [watchlist for watchlist in watchlists
                   if watchlist.get("name") == watchlist_name]
        if len(matches) != 1:
            raise TVMCPError(
                f"TradingView watchlist「{watchlist_name}」應唯一存在，實際找到 {len(matches)} 個"
            )

        watchlist = matches[0]
        if not isinstance(watchlist.get("id"), (int, str)):
            raise TVMCPError(f"TradingView watchlist「{watchlist_name}」缺少有效 ID")
        tv_symbol = self._resolve_watchlist_symbol(symbol, market)
        if tv_symbol in (watchlist.get("symbols") or []):
            return False

        result = self.call_tool("mcp-watchlist-add-to-watchlist", {
            "watchlist_id": str(watchlist["id"]),
            "symbols": [tv_symbol],
        })
        resulting_symbols = result.get("symbols") if isinstance(result, dict) else None
        if not isinstance(resulting_symbols, list) or tv_symbol not in resulting_symbols:
            raise TVMCPError(f"TradingView 未確認已將 {tv_symbol} 加入「{watchlist_name}」")
        watchlist["symbols"] = resulting_symbols
        return True

    def remove_symbol_from_watchlist(self, watchlist_name: str, symbol: str,
                                     market: str) -> bool:
        """從指定市場的 watchlist 移除標的；不存在時回傳 False。"""
        watchlists = self._watchlists_cache
        if watchlists is None:
            watchlists = self.list_watchlists()
        matches = [watchlist for watchlist in watchlists
                   if watchlist.get("name") == watchlist_name]
        if len(matches) != 1:
            raise TVMCPError(
                f"TradingView watchlist「{watchlist_name}」應唯一存在，實際找到 {len(matches)} 個"
            )

        watchlist = matches[0]
        if not isinstance(watchlist.get("id"), (int, str)):
            raise TVMCPError(f"TradingView watchlist「{watchlist_name}」缺少有效 ID")
        tv_symbol = self._resolve_watchlist_symbol(symbol, market)
        if tv_symbol not in (watchlist.get("symbols") or []):
            return False

        result = self.call_tool("mcp-watchlist-remove-from-watchlist", {
            "watchlist_id": str(watchlist["id"]),
            "symbols": [tv_symbol],
        })
        resulting_symbols = result.get("symbols") if isinstance(result, dict) else None
        if not isinstance(resulting_symbols, list) or tv_symbol in resulting_symbols:
            raise TVMCPError(f"TradingView 未確認已從「{watchlist_name}」移除 {tv_symbol}")
        watchlist["symbols"] = resulting_symbols
        return True

    def run_screener(self, market: str = "america", filters: dict | None = None,
                     sort_by: str = "volume", sort_order: str = "desc", limit: int = 100,
                     columns: list[str] | None = None, symbol_types: list[str] | None = None,
                     filter_preset: str | None = None, symbolset: list[str] | None = None) -> dict:
        args: dict[str, Any] = {"market": market, "sort_by": sort_by,
                                "sort_order": sort_order, "limit": limit}
        if filters:
            args["filters"] = filters
        if columns:
            args["columns"] = columns
        if symbol_types:
            args["symbol_types"] = symbol_types
        if filter_preset:
            args["filter_preset"] = filter_preset
        if symbolset:
            args["symbolset"] = symbolset
        return self.call_tool("mcp-tv-run-screener", args)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="TradingView MCP 客戶端")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("tools", help="列出可用工具")
    sub.add_parser("watchlists", help="列出我的 watchlist")
    p_wl = sub.add_parser("watchlist", help="取得單一 watchlist")
    p_wl.add_argument("watchlist_id")
    p_call = sub.add_parser("call", help="呼叫任意工具")
    p_call.add_argument("tool")
    p_call.add_argument("args", nargs="?", default="{}")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        client = TVMCPClient(interactive=True)
        if args.cmd == "tools":
            for t in client.list_tools():
                print(f"{t['name']:<42} {t.get('title', '')}")
        elif args.cmd == "watchlists":
            for w in client.list_watchlists():
                symbols = [s for s in (w.get("symbols") or []) if not str(s).startswith("###")]
                print(f"{w['id']:>10}  {len(symbols):>4} 檔  {w['name']}")
        elif args.cmd == "watchlist":
            print(json.dumps(client.get_watchlist(args.watchlist_id), ensure_ascii=False, indent=2))
        elif args.cmd == "call":
            print(json.dumps(client.call_tool(args.tool, json.loads(args.args)),
                             ensure_ascii=False, indent=2))
        return 0
    except (TVMCPError, tv_auth.TVAuthError) as exc:
        print(f"MCP 失敗：{exc}")
        return 1
    except json.JSONDecodeError as exc:
        print(f"args 不是合法 JSON：{exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
