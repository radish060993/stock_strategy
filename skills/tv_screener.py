"""TradingView Screener Skill：抓取 TradingView 清單並寫入 data/watchlist.md。

預設來源
    tw_screener  台股條件掃描：市值 ≥ 50 億 TWD、收盤價 ≥ SMA200（日）、
                 月成交金額 > 100 億 TWD、1 年 Beta > 1
    tw_best      台股強勢股          https://www.tradingview.com/markets/stocks-taiwan/market-movers-best-performing/
    us_screener  美股條件掃描：市值 ≥ 20 億 USD、收盤價 ≥ SMA200（日）、
                 月成交金額 > 9 億 USD、1 年 Beta > 1
    us_best      美股強勢股          https://www.tradingview.com/markets/stocks-usa/market-movers-best-performing/

來源類型（kind）
    html          抓頁面 HTML，解析 <tr data-rowkey="EXCHANGE:SYMBOL">。market-movers 為
                  伺服器端渲染可直接取得；自訂 screener 頁面為前端渲染且未登入會回 404。
    scan          POST 條件 payload 到 scanner.tradingview.com/<market>/scan；預設條件內建，
                  其他 scan 來源仍可使用 data/tv_scans/<key>.json。
    mcp_watchlist 透過 OAuth 2.1 + 官方 MCP 讀取自己的 watchlist（params: watchlist_id）。
    mcp_screener  透過 MCP 執行 screener（params 直接傳給 run_screener，如 market/filters/sort_by）。

    html 來源失敗時會退回 scanner payload；預設 scanner 來源不需登入。
    mcp_* 來源需先執行：python -m skills.tv_auth login

    註：TradingView MCP 未提供「以分享 ID 載入已存 screener」的工具，watchlist id 必須是數字，
    因此 /screener/<id>/ 這類私人 screener 無法直接取得，請改用 mcp_watchlist 或 mcp_screener。

自訂來源
    建立 data/tv_sources.json 覆寫預設，格式見 DEFAULT_SOURCES 或 README 範例：
        [{"key": "us_rs", "market": "US", "kind": "mcp_screener",
          "params": {"market": "america", "filters": {"Perf.Y": [50, null]},
                     "sort_by": "Perf.Y", "limit": 100}}]

寫入規則
    - 使用者手動加入的列（note 不以 "tv:" 開頭）永遠保留且排在前面
    - 自動列的 note 為 "tv:<來源,...>"；每次成功抓取的來源會整批替換
    - 抓取失敗的來源保留上一次的自動列（寧可沿用舊清單，不要清空）
    - 所有來源都失敗時不改寫檔案

用法
    python -m skills.tv_screener            # 抓取並寫入
    python -m skills.tv_screener --dry-run  # 只印出結果
    python -m skills.tv_screener --sources tw_best,us_best
"""
from __future__ import annotations

import argparse
import html
import json
import logging
import os
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import requests

from .tv_auth import TVAuthError
from .tv_mcp import TVMCPClient, TVMCPError

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
WATCHLIST = ROOT / "data" / "watchlist.md"
SCAN_DIR = ROOT / "data" / "tv_scans"
SOURCES_FILE = ROOT / "data" / "tv_sources.json"
NO_DATA_MSG = "Tradingview無資料"
AUTO_PREFIX = "tv:"

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"),
    "Accept-Language": "en-US,en;q=0.9",
}

TW_EXCHANGES = {"TWSE": ".TW", "TPEX": ".TWO"}
US_EXCHANGES = {"NASDAQ", "NYSE", "AMEX", "NYSE ARCA", "NYSEARCA", "CBOE", "BATS"}

ROW_RE = re.compile(r'<tr[^>]*\bdata-rowkey="([^"]+)"[^>]*>(.*?)</tr>', re.S)
TITLE_RE = re.compile(r'title="[^"]*?\s[\u2212\-]\s([^"]+)"')


class TVNoData(Exception):
    pass


@dataclass(frozen=True)
class Source:
    key: str
    market: str  # TW / US
    url: str = ""
    kind: str = "html"  # html | scan | mcp_watchlist | mcp_screener
    params: dict = field(default_factory=dict)

    @property
    def scanner_market(self) -> str:
        return "taiwan" if self.market == "TW" else "america"

    @property
    def needs_mcp(self) -> bool:
        return self.kind.startswith("mcp_")


DEFAULT_SOURCES = [
    Source("tw_screener", "TW", kind="scan", params={
        "filter": [
            {"left": "market_cap_basic", "operation": "egreater", "right": 5_000_000_000},
            {"left": "close", "operation": "egreater", "right": "SMA200"},
            {"left": "Value.Traded|1M", "operation": "greater", "right": 10_000_000_000},
            {"left": "beta_1_year", "operation": "greater", "right": 1},
        ],
        "options": {"lang": "en"},
        "symbols": {"query": {"types": []}, "tickers": []},
        "columns": ["description"],
        "sort": {"sortBy": "market_cap_basic", "sortOrder": "desc"},
        "range": [0, 500],
    }),
    Source("tw_best", "TW", "https://www.tradingview.com/markets/stocks-taiwan/market-movers-best-performing/"),
    Source("us_screener", "US", kind="scan", params={
        "filter": [
            {"left": "market_cap_basic", "operation": "egreater", "right": 2_000_000_000},
            {"left": "close", "operation": "egreater", "right": "SMA200"},
            {"left": "Value.Traded|1M", "operation": "greater", "right": 900_000_000},
            {"left": "beta_1_year", "operation": "greater", "right": 1},
        ],
        "options": {"lang": "en"},
        "symbols": {"query": {"types": []}, "tickers": []},
        "columns": ["description"],
        "sort": {"sortBy": "market_cap_basic", "sortOrder": "desc"},
        "range": [0, 500],
    }),
    Source("us_best", "US", "https://www.tradingview.com/markets/stocks-usa/market-movers-best-performing/"),
]


def load_sources(path: Path = SOURCES_FILE) -> list[Source]:
    """讀取 data/tv_sources.json；不存在或格式錯誤時使用預設來源。"""
    if not path.exists():
        return list(DEFAULT_SOURCES)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        sources = [
            Source(key=item["key"], market=item["market"].upper(), url=item.get("url", ""),
                   kind=item.get("kind", "html"), params=item.get("params", {}))
            for item in raw
        ]
    except (json.JSONDecodeError, OSError, KeyError, AttributeError, TypeError) as exc:
        log.warning("%s 格式錯誤（%s），改用預設來源", path.name, exc)
        return list(DEFAULT_SOURCES)
    if not sources:
        log.warning("%s 沒有任何來源，改用預設來源", path.name)
        return list(DEFAULT_SOURCES)
    return sources


# 相容舊呼叫端
SOURCES = DEFAULT_SOURCES


@dataclass
class Row:
    symbol: str
    market: str
    name: str = ""
    note: str = ""
    sources: list[str] = field(default_factory=list)

    @property
    def is_auto(self) -> bool:
        return self.note.startswith(AUTO_PREFIX)


# ---------------------------------------------------------------------------
# 代碼轉換
# ---------------------------------------------------------------------------

def detect_market(tv_symbol: str) -> str | None:
    """由 TradingView 交易所代碼判斷市場；無法判斷回傳 None。"""
    if ":" not in tv_symbol:
        return None
    exchange = tv_symbol.split(":", 1)[0].upper()
    if exchange in TW_EXCHANGES:
        return "TW"
    return "US" if exchange in US_EXCHANGES else None


def to_yahoo_symbol(tv_symbol: str, market: str) -> str | None:
    """TradingView 'EXCHANGE:SYMBOL' → yfinance 代碼；非目標市場回傳 None。

    market="AUTO" 時依交易所自動判斷（同一份 watchlist 可能混合台股與美股）。
    """
    if ":" not in tv_symbol:
        return None
    exchange, sym = tv_symbol.split(":", 1)
    exchange, sym = exchange.upper(), sym.upper()
    if market == "AUTO":
        detected = detect_market(tv_symbol)
        if detected is None:
            return None
        market = detected
    if market == "TW":
        suffix = TW_EXCHANGES.get(exchange)
        return f"{sym}{suffix}" if suffix else None
    if exchange in US_EXCHANGES:
        return sym.replace(".", "-").replace("/", "-")  # BRK.B → BRK-B
    return None


def _clean_name(name: str) -> str:
    return html.unescape(name).replace("|", "/").strip()


# ---------------------------------------------------------------------------
# 抓取
# ---------------------------------------------------------------------------

def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HEADERS)
    sid = os.getenv("TV_SESSIONID")
    if sid:
        s.cookies.set("sessionid", sid, domain=".tradingview.com")
    return s


def parse_html(text: str) -> list[tuple[str, str]]:
    """回傳 [(TV 代碼, 名稱)]。"""
    out = []
    for rowkey, body in ROW_RE.findall(text):
        m = TITLE_RE.search(body)
        out.append((html.unescape(rowkey), _clean_name(m.group(1)) if m else ""))
    return out


def fetch_html(src: Source, session: requests.Session, timeout: float) -> list[tuple[str, str]]:
    resp = session.get(src.url, timeout=timeout)
    if resp.status_code != 200:
        raise TVNoData(f"HTTP {resp.status_code}")
    rows = parse_html(resp.text)
    if not rows:
        raise TVNoData("頁面中沒有清單資料（可能需登入或為前端渲染）")
    return rows


def fetch_scan(src: Source, session: requests.Session, timeout: float) -> list[tuple[str, str]]:
    payload_file = SCAN_DIR / f"{src.key}.json"
    if src.params:
        payload = json.loads(json.dumps(src.params))
    elif payload_file.exists():
        payload = json.loads(payload_file.read_text(encoding="utf-8"))
    else:
        raise TVNoData(f"無 scanner payload（data/tv_scans/{payload_file.name}）")
    columns = payload.get("columns") or []
    if "description" not in columns:
        payload["columns"] = columns + ["description"]
    name_idx = payload["columns"].index("description")

    resp = session.post(f"https://scanner.tradingview.com/{src.scanner_market}/scan",
                        json=payload, timeout=timeout)
    if resp.status_code != 200:
        raise TVNoData(f"scanner HTTP {resp.status_code}: {resp.text[:120]}")
    data = resp.json().get("data") or []
    if not data:
        raise TVNoData("scanner 回傳空清單")
    return [(item["s"], _clean_name(str((item.get("d") or [""] * (name_idx + 1))[name_idx] or "")))
            for item in data if item.get("s")]


def fetch_mcp_watchlist(src: Source, client: TVMCPClient) -> list[tuple[str, str]]:
    watchlist_id = src.params.get("watchlist_id")
    if not watchlist_id:
        raise TVNoData("mcp_watchlist 來源缺少 params.watchlist_id")
    if not str(watchlist_id).isdigit():
        raise TVNoData(f"watchlist_id 必須為數字，取得 {watchlist_id!r}"
                       "（TradingView 不支援以 screener 分享 ID 查詢）")
    data = client.get_watchlist(watchlist_id)
    # 以 ### 開頭的項目是使用者在 watchlist 中的分隔標題，不是標的
    symbols = [s for s in (data.get("symbols") or []) if not str(s).startswith("###")]
    if not symbols:
        raise TVNoData(f"watchlist {watchlist_id} 沒有標的")
    return [(s, "") for s in symbols]


def fetch_mcp_screener(src: Source, client: TVMCPClient) -> list[tuple[str, str]]:
    params = dict(src.params)
    params.setdefault("market", "taiwan" if src.market == "TW" else "america")
    result = client.run_screener(**params)
    data = result.get("data", result)
    rows = data.get("rows") or []
    if not rows:
        raise TVNoData("screener 回傳空清單")
    if ignored := data.get("ignored_filters"):
        log.warning("[%s] 以下 filter 被忽略（欄位名稱可能有誤）: %s", src.key, ignored)
    return [(r["symbol"], str(r.get("description") or r.get("name") or ""))
            for r in rows if r.get("symbol")]


def fetch_source(src: Source, session: requests.Session | None = None,
                 timeout: float = 20.0, client: TVMCPClient | None = None) -> list[Row]:
    """抓取單一來源，失敗時丟出 TVNoData（其他例外也會包成 TVNoData）。"""
    if src.needs_mcp:
        if client is None:
            raise TVNoData("需要 MCP 授權，請先執行：python -m skills.tv_auth login")
        fetchers = [fetch_mcp_watchlist if src.kind == "mcp_watchlist" else fetch_mcp_screener]
        args = (src, client)
    else:
        session = session or _session()
        fetchers = [fetch_html] if src.kind == "html" else [fetch_scan]
        if src.kind == "html":
            fetchers.append(fetch_scan)  # HTML 失敗時退回 scanner payload
        args = (src, session, timeout)

    errors = []
    for fetcher in fetchers:
        try:
            raw = fetcher(*args)
        except (TVNoData, TVMCPError, TVAuthError) as exc:
            errors.append(str(exc))
            continue
        except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
            errors.append(f"{type(exc).__name__}: {exc}")
            continue

        rows, seen = [], set()
        for tv_sym, name in raw:
            sym = to_yahoo_symbol(tv_sym, src.market)
            if sym and sym not in seen:
                seen.add(sym)
                rows.append(Row(sym, detect_market(tv_sym) or src.market, name, sources=[src.key]))
        if rows:
            return rows
        errors.append("沒有可轉換的代碼")
    raise TVNoData("；".join(errors))


def fetch_all(sources: list[Source] | None = None) -> tuple[dict[str, list[Row]], dict[str, str]]:
    """回傳 (成功來源 → 列表, 失敗來源 → 原因)。"""
    sources = sources if sources is not None else load_sources()
    ok: dict[str, list[Row]] = {}
    failed: dict[str, str] = {}
    session = _session()

    client = None
    if any(s.needs_mcp for s in sources):
        try:
            client = TVMCPClient()
        except (TVMCPError, TVAuthError) as exc:
            log.warning("MCP 未授權: %s", exc)

    for src in sources:
        try:
            ok[src.key] = fetch_source(src, session, client=client)
            log.info("[%s] 取得 %d 檔", src.key, len(ok[src.key]))
        except TVNoData as exc:
            failed[src.key] = str(exc)
            print(f"{NO_DATA_MSG}（{src.key}: {exc}）")
        except Exception as exc:  # 最後防線，單一來源錯誤不影響其他來源
            failed[src.key] = f"{type(exc).__name__}: {exc}"
            print(f"{NO_DATA_MSG}（{src.key}: {type(exc).__name__}）")
            log.exception("[%s] 未預期錯誤", src.key)
    return ok, failed


# ---------------------------------------------------------------------------
# watchlist.md 讀寫
# ---------------------------------------------------------------------------

def read_watchlist(path: Path = WATCHLIST) -> list[Row]:
    rows: list[Row] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s.startswith("|"):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if len(cells) < 2 or not cells[0] or cells[0].lower() == "symbol" or set(cells[0]) <= set("-: "):
            continue
        cells += [""] * (4 - len(cells))
        note = cells[3]
        sources = note[len(AUTO_PREFIX):].split(",") if note.startswith(AUTO_PREFIX) else []
        rows.append(Row(cells[0], cells[1].upper(), cells[2], note, sources))
    return rows


def merge_rows(existing: list[Row], fetched: dict[str, list[Row]]) -> list[Row]:
    merged: dict[str, Row] = {}

    def add(row: Row, sources: list[str]) -> None:
        key = row.symbol.upper()
        if key in merged:
            cur = merged[key]
            if cur.is_auto:
                cur.sources = list(dict.fromkeys(cur.sources + sources))
                cur.note = AUTO_PREFIX + ",".join(cur.sources)
                cur.name = cur.name or row.name
            return
        merged[key] = Row(row.symbol, row.market, row.name,
                          AUTO_PREFIX + ",".join(sources) if sources else row.note, list(sources))

    for row in existing:
        if not row.is_auto:
            add(row, [])

    for rows in fetched.values():
        for row in rows:
            add(row, row.sources)

    # 抓取失敗的來源：沿用上次結果
    for row in existing:
        if row.is_auto:
            stale = [s for s in row.sources if s not in fetched]
            if stale:
                add(row, stale)
    return list(merged.values())


def render_watchlist(rows: list[Row]) -> str:
    lines = [
        "# Watchlist",
        "",
        "以表格維護。`market` 填 `TW` 或 `US`；台股代號需含 `.TW`（上市）或 `.TWO`（上櫃）。",
        "以 `#` 開頭的 symbol 會被略過。",
        f"`note` 以 `{AUTO_PREFIX}` 開頭的列由 `skills/tv_screener.py` 自動維護，會被覆寫；手動加入的列請勿使用此前綴。",
        "",
        "| symbol | market | name | note |",
        "|--------|--------|------|------|",
    ]
    lines += [f"| {r.symbol} | {r.market} | {r.name} | {r.note} |" for r in rows]
    return "\n".join(lines) + "\n"


def write_watchlist(rows: list[Row], path: Path = WATCHLIST) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = render_watchlist(rows)
    if path.exists():
        existing = path.read_text(encoding="utf-8")
        table_start = re.search(r"^\|\s*symbol\s*\|", existing, re.M | re.I)
        if table_start:
            new_table = content[content.index("| symbol |"):]
            content = existing[:table_start.start()] + new_table
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
        f.write(content)
    os.replace(tmp, path)


def update_watchlist(dry_run: bool = False, path: Path = WATCHLIST,
                     sources: list[Source] | None = None,
                     require_all: bool = False) -> list[Row] | None:
    """抓取所有來源並更新 watchlist；全部失敗時回傳 None 且不改寫檔案。"""
    fetched, failed = fetch_all(sources)
    if require_all and failed:
        raise TVNoData("清單更新未完成：" + "；".join(
            f"{key}: {reason}" for key, reason in failed.items()
        ))
    if not fetched:
        print(NO_DATA_MSG)
        return None
    rows = merge_rows(read_watchlist(path), fetched)
    if dry_run:
        print(render_watchlist(rows))
    else:
        write_watchlist(rows, path)
    failed_sources = list(failed) or ["無"]
    log.info("watchlist 共 %d 檔（成功 %s；失敗 %s）",
             len(rows), list(fetched), failed_sources)
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="抓取 TradingView 清單並寫入 data/watchlist.md")
    parser.add_argument("--dry-run", action="store_true", help="只印出結果，不寫檔")
    parser.add_argument("--sources", help="只抓取指定來源（以逗號分隔的 key）")
    parser.add_argument("--list-sources", action="store_true", help="列出目前設定的來源")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    try:
        sources = load_sources()
        if args.list_sources:
            for s in sources:
                print(f"{s.key:<14} {s.market}  {s.kind:<14} {s.url or s.params}")
            return 0
        if args.sources:
            wanted = {k.strip() for k in args.sources.split(",") if k.strip()}
            unknown = wanted - {s.key for s in sources}
            if unknown:
                print(f"未知的來源: {', '.join(sorted(unknown))}")
                return 1
            sources = [s for s in sources if s.key in wanted]
        return 0 if update_watchlist(dry_run=args.dry_run, sources=sources) is not None else 1
    except Exception:
        print(NO_DATA_MSG)
        log.exception("更新 watchlist 失敗")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
