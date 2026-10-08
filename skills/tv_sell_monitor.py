"""Monitor the TradingView "賣出提醒" watchlist for weekly red volume bars."""
from __future__ import annotations

import json
import logging
import math
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from filelock import FileLock, Timeout

from . import notify, tv_mcp, tv_screener

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
STATE_FILE = ROOT / "data" / "cache" / "sell_volume_states.json"
WATCHLIST_NAME = "賣出提醒"
MAX_BAR_AGE = timedelta(days=7)


def _market_for_symbol(symbol: str) -> str | None:
    exchange = symbol.split(":", 1)[0].upper() if ":" in symbol else ""
    if exchange == "OANDA":
        return "US"
    return tv_screener.detect_market(symbol)


def _load_states() -> dict[str, dict[str, int | bool]]:
    if not STATE_FILE.exists():
        return {}
    try:
        with FileLock(str(STATE_FILE.with_suffix(".json.lock")), timeout=10):
            data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, Timeout, json.JSONDecodeError) as exc:
        raise ValueError(f"無法讀取週線顏色狀態：{exc}") from exc
    if not isinstance(data, dict) or any(
        not isinstance(symbol, str)
        or not isinstance(state, dict)
        or not isinstance(state.get("bar_time"), int)
        or isinstance(state.get("bar_time"), bool)
        or not isinstance(state.get("red"), bool)
        for symbol, state in data.items()
    ):
        raise ValueError("週線顏色狀態檔格式錯誤")
    return data


def _save_states(states: dict[str, dict[str, int | bool]]) -> None:
    temporary_path: str | None = None
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with FileLock(str(STATE_FILE.with_suffix(".json.lock")), timeout=10):
            fd, temporary_path = tempfile.mkstemp(
                dir=STATE_FILE.parent, suffix=".tmp"
            )
            with os.fdopen(fd, "w", encoding="utf-8") as file:
                json.dump(states, file, ensure_ascii=False, indent=2, sort_keys=True)
            os.replace(temporary_path, STATE_FILE)
            temporary_path = None
    except Timeout as exc:
        raise OSError(f"等待週線顏色狀態鎖逾時：{exc}") from exc
    finally:
        if temporary_path is not None:
            try:
                os.unlink(temporary_path)
            except FileNotFoundError:
                pass


def _latest_weekly_bar(client: tv_mcp.TVMCPClient, symbol: str,
                       now: datetime) -> tuple[int, bool]:
    result = client.call_tool("mcp-tv-get-ohlcv", {
        "symbol": symbol,
        "interval": "1W",
        "count": 2,
    })
    bars = result.get("bars") if isinstance(result, dict) else None
    if not isinstance(bars, list) or not bars:
        raise ValueError("TradingView 週線 OHLCV 為空")
    if any(
        not isinstance(item, dict)
        or not isinstance(item.get("t"), int)
        or isinstance(item.get("t"), bool)
        for item in bars
    ):
        raise ValueError("TradingView 週線 OHLCV 格式錯誤")
    bar = max(bars, key=lambda item: item["t"])
    timestamp = bar.get("t")
    opening, closing = bar.get("o"), bar.get("c")
    if (not isinstance(timestamp, int) or isinstance(timestamp, bool)
            or not isinstance(opening, (int, float)) or isinstance(opening, bool)
            or not isinstance(closing, (int, float)) or isinstance(closing, bool)
            or not math.isfinite(opening) or not math.isfinite(closing)
            or opening <= 0 or closing <= 0):
        raise ValueError("TradingView 週線 OHLCV 缺值或數值無效")
    bar_time = datetime.fromtimestamp(timestamp, timezone.utc)
    age = now.astimezone(timezone.utc) - bar_time
    if age < timedelta(minutes=-1) or age > MAX_BAR_AGE:
        raise ValueError(f"TradingView 最新週 K 時間過期或在未來：{bar_time.isoformat()}")
    return timestamp, closing < opening


def check_watchlist(now: datetime, cooldown_minutes: int = 30,
                    dry_run: bool = False) -> list[str]:
    """Check the named TradingView list and return history-ready status lines."""
    if now.tzinfo is None:
        raise ValueError("執行時間必須包含時區")

    client = tv_mcp.TVMCPClient()
    watchlists = client.list_watchlists()
    if not isinstance(watchlists, list) or any(
        not isinstance(item, dict) for item in watchlists
    ):
        raise tv_mcp.TVMCPError("TradingView watchlist 清單回應格式錯誤")
    matches = [item for item in watchlists if item.get("name") == WATCHLIST_NAME]
    if len(matches) != 1:
        raise tv_mcp.TVMCPError(
            f"TradingView watchlist「{WATCHLIST_NAME}」應唯一存在，實際找到 {len(matches)} 個"
        )

    symbols = matches[0].get("symbols")
    if (not isinstance(symbols, list)
            or any(not isinstance(symbol, str) or not symbol for symbol in symbols)):
        raise tv_mcp.TVMCPError(
            f"TradingView watchlist「{WATCHLIST_NAME}」缺少有效 symbols"
        )
    symbols = list(dict.fromkeys(
        symbol for symbol in symbols
        if not symbol.startswith("###")
    ))
    if not symbols:
        return [f"TradingView「{WATCHLIST_NAME}」清單為空，未檢查週線"]

    states = _load_states()
    current_symbols = set(symbols)
    stale_symbols = set(states) - current_symbols
    for symbol in stale_symbols:
        del states[symbol]
    records: list[str] = []
    updated = bool(stale_symbols)
    for symbol in symbols:
        market = _market_for_symbol(symbol)
        if market is None:
            records.append(f"**{symbol}**｜無數據：無法辨識市場")
            continue
        if notify.is_market_opening_cooloff(market, now):
            records.append(f"**{symbol}**｜{market} 開盤冷卻時段，略過週線查詢與通知")
            continue
        try:
            bar_time, red = _latest_weekly_bar(client, symbol, now)
        except (tv_mcp.TVMCPError, ValueError, OverflowError) as exc:
            line = f"**{symbol}**｜無數據：週線資料無效或不可用（{exc}）"
            log.warning("%s", line)
            records.append(line)
            continue

        previous = states.get(symbol)
        turned_red = (
            previous is not None
            and previous["red"] is False
            and red
        )
        status = "紅色" if red else "綠色"
        if turned_red:
            message = (
                f"TradingView「{WATCHLIST_NAME}」週線成交量柱轉紅\n"
                f"{symbol}\n週 K 時間 {datetime.fromtimestamp(bar_time, timezone.utc).isoformat()}"
            )
            result = notify.notify(
                symbol, message, cooldown_minutes=cooldown_minutes,
                now=now, dry_run=True if dry_run else None,
            )
            records.append(
                f"**{symbol}**｜週線成交量柱由綠轉紅｜通知結果 {result}"
                f"｜週 K 時間 {datetime.fromtimestamp(bar_time, timezone.utc).isoformat()}"
            )
            if result == notify.SENT:
                states[symbol] = {"bar_time": bar_time, "red": True}
                updated = True
        else:
            records.append(
                f"**{symbol}**｜週線成交量柱 {status}"
                f"｜週 K 時間 {datetime.fromtimestamp(bar_time, timezone.utc).isoformat()}"
            )
            if previous is None or previous["bar_time"] != bar_time or previous["red"] != red:
                states[symbol] = {"bar_time": bar_time, "red": red}
                updated = True

    if updated:
        _save_states(states)
    return records
