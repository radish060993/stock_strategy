"""台股 + 美股 盯盤 Agent 主程式（Hermes 模式）。

建議由Windows 工作排程器 每 10 分鐘觸發一次；
程式內部會：
  1. 用 filelock 確保同時間只有一個執行個體
  2. 依 rules.md 的 run_interval_minutes（預設 10 分鐘）自行節流
  3. 只檢查各市場設定的盤前、盤中或盤後時段
     監控 TradingView「賣出提醒」清單週線量柱轉紅，再更新一般 TradingView 清單
     任一一般清單來源失敗時，停止該市場的一般訊號監控
  4. 三個周線指標與周線技能過濾同時通過才推播：
     Darvas 非紅色、Squeeze 為 lime/green/maroon、Kalman trend_strength >= -10、
     當前報價 > 前一根已確認周 K 計算出的 Kalman line、現價相對線的帶方向價差 < 7%
     周線過濾：MA10 > MA20、實體幅度 <= 8%、
     前 6 週（不含本週）至少 3 週量柱為綠（Close >= Open）
  5. 將結果追加到 data/history/YYYY-MM-DD.md（長期記憶）

指標使用最近 5 年日 K 彙整的周線，包含當前尚未收完的周 K。
Adaptive Kalman Trend 使用最近已確認周 K，當前報價只用於價格位置與價差判斷。
盤中與延長時段報價須為當地今天且不超過 15 分鐘；指標歷史資料不可超過 7 天。
資料不足、缺值或異常時不通知。這不是僅在訊號轉換時通知；
每輪先完成整份監控清單的過濾，再彙整通過標的通知；條件持續成立時，
仍依各標的 cooldown 控制通知頻率。

用法：
    python run_agent.py                # 正常執行
    python run_agent.py --market TW    # 只處理台股清單
    python run_agent.py --market US    # 只處理美股清單
    python run_agent.py --force        # 忽略 10 分鐘節流
    python run_agent.py --all-markets  # 忽略開盤時間過濾
    python run_agent.py --dry-run      # 不實際推播
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import os
import re
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from filelock import FileLock, Timeout

import numpy as np
import pandas as pd

from skills import indicators
from skills import notify as notifier
from skills import tv_screener
from skills import tv_sell_monitor
from skills import tv_mcp

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
CACHE = DATA / "cache"
HISTORY = DATA / "history"
LOCK_FILE = CACHE / "agent_run.lock"
LAST_RUN_FILE = CACHE / "last_run.json"

HISTORY_RETENTION_DAYS = 14
WATCHLIST_FAILURE_LIMIT = 3

INTERVAL_TOLERANCE = timedelta(seconds=30)  # 排程器時間抖動容忍

TPE = ZoneInfo("Asia/Taipei")
NYC = ZoneInfo("America/New_York")
MARKETS = {
    "TW": (TPE, time(9, 0), time(13, 30)),
    "US": (NYC, time(9, 30), time(16, 0)),
}
US_PREMARKET_START = time(4, 0)
US_AFTER_HOURS_END = time(20, 0)
HISTORY_MAX_AGE = timedelta(days=7)

log = logging.getLogger("agent")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class Rules:
    cooldown_minutes: int = 30
    run_interval_minutes: int = 10
    market_hours_only: bool = True


@dataclass
class Stock:
    symbol: str
    market: str
    name: str = ""


@dataclass
class Quote:
    price: float
    as_of: datetime

@dataclass(frozen=True)
class WeeklySignal:
    passed: bool
    summary: str
    reason: str


# ---------- 記憶載入 ----------

def load_rules(path: Path = ROOT / "rules.md") -> Rules:
    rules = Rules()
    if not path.exists():
        return rules
    for m in re.finditer(r"^\s*[-*]?\s*(\w+)\s*:\s*(\S+)\s*$", path.read_text(encoding="utf-8"), re.M):
        key, raw = m.group(1), m.group(2)
        if not hasattr(rules, key):
            continue
        default = getattr(rules, key)
        try:
            if isinstance(default, bool):
                value = raw.lower() in ("true", "yes", "1", "on")
            else:
                value = type(default)(raw)
        except ValueError:
            log.warning("rules.md 的 %s=%s 無法解析，使用預設 %s", key, raw, default)
            continue
        setattr(rules, key, value)

    return rules


def load_watchlist(path: Path = DATA / "watchlist.md") -> list[Stock]:
    stocks: list[Stock] = []
    if not path.exists():
        return stocks
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 2 or not cells[0] or cells[0].lower() == "symbol" or set(cells[0]) <= set("-: "):
            continue
        if cells[0].startswith("#"):
            continue
        market = cells[1].upper()
        if market not in MARKETS:
            log.warning("未知市場 %s（%s），略過", market, cells[0])
            continue
        stocks.append(Stock(cells[0].upper(), market, cells[2] if len(cells) > 2 else ""))
    return stocks


# ---------- 過濾邏輯 ----------

def last_run_path(market: str | None = None) -> Path:
    return CACHE / f"last_run_{market}.json" if market else LAST_RUN_FILE


def should_run(now: datetime, interval_minutes: int, market: str | None = None) -> bool:
    """距離上次實際執行未滿 interval 就跳過。"""
    path = last_run_path(market)
    if not path.exists():
        return True
    try:
        last = datetime.fromisoformat(json.loads(path.read_text(encoding="utf-8"))["last_run"])
    except (json.JSONDecodeError, KeyError, ValueError, OSError):
        return True
    return now - last >= timedelta(minutes=interval_minutes) - INTERVAL_TOLERANCE


def mark_run(now: datetime, market: str | None = None) -> None:
    last_run_path(market).write_text(json.dumps({"last_run": now.isoformat()}), encoding="utf-8")


def is_monitoring_window(market: str, now: datetime) -> bool:
    """Return whether this market's configured monitoring window is active."""
    if market == "TW":
        local = now.astimezone(TPE)
        current = local.time()
        return local.weekday() < 5 and (
            (local.hour == 8 and local.minute == 0)
            or time(9, 0) <= current < time(13, 31)
        )
    if market == "US":
        local = now.astimezone(NYC)
        current = local.time()
        return local.weekday() < 5 and US_PREMARKET_START <= current < US_AFTER_HOURS_END
    raise ValueError(f"未知市場: {market}")


# ---------- 數據 ----------

def fetch_price_history(stock: Stock, period: str, interval: str = "1d",
                        prepost: bool = False) -> pd.DataFrame | None:
    try:
        import yfinance as yf
    except ImportError:
        log.error("未安裝 yfinance")
        return None
    try:
        df = yf.Ticker(stock.symbol).history(
            period=period, interval=interval, auto_adjust=False, prepost=prepost
        )
    except Exception as exc:  # yfinance 會丟各種例外
        log.warning("[%s] 取價失敗: %s", stock.symbol, exc)
        return None
    if df is None or df.empty:
        log.info("[%s] 無回傳資料", stock.symbol)
        return None
    return df


def fetch_quote(stock: Stock, now: datetime) -> Quote | None:
    """取得最新盤中或延長時段報價；任何疑慮一律視為無數據。"""
    df = fetch_price_history(stock, "1d", interval="1m", prepost=True)
    if df is None:
        return None
    df = df.dropna(subset=["Close"])
    if df.empty:
        log.info("[%s] 沒有有效的分鐘報價", stock.symbol)
        return None

    tz = MARKETS[stock.market][0]
    last_ts = df.index[-1].to_pydatetime()
    now_local = now.astimezone(tz)
    if last_ts.tzinfo is None:
        log.info("[%s] 報價時間沒有時區，視為無數據", stock.symbol)
        return None
    quote_local = last_ts.astimezone(tz)
    if quote_local.date() != now_local.date():
        log.info("[%s] 最新報價日期 %s 不是今天，視為無數據", stock.symbol, quote_local.date())
        return None
    age = now - last_ts.astimezone(timezone.utc)
    if age < timedelta(minutes=-1):
        log.info("[%s] 報價時間在未來（%s），視為無數據", stock.symbol, last_ts)
        return None

    price = float(df["Close"].iloc[-1])
    if not (math.isfinite(price) and price > 0):
        log.info("[%s] 價格異常 price=%s", stock.symbol, price)
        return None
    return Quote(price=price, as_of=last_ts)


def evaluate_weekly_signal(
        df: pd.DataFrame, current_price: float | None = None,
        kalman_input: pd.DataFrame | None = None) -> WeeklySignal:
    """使用同一份周線計算指標與技能過濾；缺值或未知狀態不通過。"""
    data = indicators.normalize_ohlcv(df)
    if data.empty or data.index.hasnans or data.index.has_duplicates:
        raise ValueError("OHLC 資料為空或時間索引異常")
    prices = data[["Open", "High", "Low", "Close"]].to_numpy(dtype=float)
    if not np.isfinite(prices).all() or (prices <= 0).any():
        raise ValueError("OHLC 含缺值、非有限數值或非正價格")
    if "Volume" not in data.columns:
        raise ValueError("周線技能過濾缺少 Volume 資料")
    volume = data["Volume"].to_numpy(dtype=float)
    if not np.isfinite(volume).all() or (volume < 0).any():
        raise ValueError("Volume 含缺值、非有限數值或負成交量")
    if current_price is None:
        current_price = float(data["Close"].iloc[-1])
    if not math.isfinite(current_price) or current_price <= 0:
        raise ValueError("現價含缺值、非有限數值或非正價格")

    weekly = indicators.to_weekly(data)
    darvas = indicators.darvas_box_series(weekly).iloc[-1]
    squeeze_series = indicators.squeeze_momentum_series(weekly)
    if len(squeeze_series) < 2:
        raise ValueError("指標資料不足，無法判定 Squeeze 前值")
    squeeze = squeeze_series.iloc[-1]
    kalman_data = indicators.normalize_ohlcv(kalman_input) if kalman_input is not None else weekly.copy()
    if kalman_data.empty or kalman_data.index.hasnans or kalman_data.index.has_duplicates:
        raise ValueError("Kalman 資料為空或時間索引異常")
    kalman_closes = kalman_data["Close"].to_numpy(dtype=float)
    if not np.isfinite(kalman_closes).all() or (kalman_closes <= 0).any():
        raise ValueError("Kalman Close 含缺值、非有限數值或非正價格")
    kalman = indicators.kalman_trend_series(
        kalman_data, measurement_noise=30.0, osc_smooth=5,
        trend_lookback=20, strength_smooth=10, model="standard",
    ).iloc[-1]
    values = [
        darvas["top"], darvas["bottom"], squeeze["val"],
        squeeze_series["val"].iloc[-2], kalman["kalman"], kalman["trend_strength"],
        kalman["oscillator"],
    ]
    if not np.isfinite(np.asarray(values, dtype=float)).all():
        raise ValueError("指標無有效數值（Box 尚未形成或指標資料不足）")
    if (darvas["color"] not in ("green", "yellow", "red")
            or squeeze["color"] not in ("lime", "green", "maroon", "red")
            or kalman["color"] not in ("green", "red", "blue")):
        raise ValueError("指標顏色未知")
    if kalman["kalman"] <= 0:
        raise ValueError("Kalman line 必須為正數")

    kalman_price_gap_pct = (current_price - kalman["kalman"]) / kalman["kalman"] * 100
    checks = {
        "Darvas 非紅色": darvas["color"] in ("green", "yellow"),
        "Squeeze 非紅色": squeeze["color"] in ("lime", "green", "maroon"),
        "Kalman 趨勢強度 >= -10": kalman["trend_strength"] >= -10,
        "當前價 > Kalman line": current_price > kalman["kalman"],
        "現價與 Kalman line 價差 < 7%": kalman_price_gap_pct < 7,
    }
    filters = indicators.calculate_weekly_filters(weekly)
    filter_names = {
        "ma_trend": "周線 MA10 > MA20",
        "doji": "周線實體幅度 <= 8%",
        "volume_green": "前 6 週至少 3 週綠色量柱",
        "not_consecutive_red_volume": "本週與上週不可連續紅色量柱",
    }
    for key, name in filter_names.items():
        checks[name] = filters["checks"][key]
    checks["周線技能過濾"] = filters["passed"]
    summary = (
        f"周線（含未收完當週；周 K 標籤 {weekly.index[-1]:%Y-%m-%d}）"
        f"｜Darvas {darvas['color']}（上緣 {darvas['top']:.2f}、下緣 {darvas['bottom']:.2f}）"
        f"｜Squeeze {squeeze['color']}（動能 {squeeze['val']:.2f}）"
        f"｜Kalman {kalman['color']}（已確認周 K；周 K 標籤 {kalman_data.index[-1]:%Y-%m-%d}，"
        f"趨勢強度 {kalman['trend_strength']:.2f}、Kalman line {kalman['kalman']:.2f}）"
        f"｜現價與 Kalman line 價差 {kalman_price_gap_pct:.2f}%"
        f"｜周線過濾 {'通過' if filters['passed'] else '未通過'}"
        f"（MA10 {filters['ma10']:.2f}、MA20 {filters['ma20']:.2f}、"
        f"實體 {filters['body_pct']:.2f}%、"
        f"前 6 週綠色量柱 {filters['green_volume_weeks']} 週）"
    )
    failed = [name for name, passed in checks.items() if not passed]
    return WeeklySignal(
        passed=not failed,
        summary=summary,
        reason="三個周線指標與周線技能過濾同時通過" if not failed else "未通過：" + "、".join(failed),
    )


def build_kalman_input(data: pd.DataFrame, as_of: datetime, market: str) -> pd.DataFrame:
    """Use confirmed weekly bars; include Friday only after its market close."""
    normalized = indicators.normalize_ohlcv(data)
    local = as_of.astimezone(MARKETS[market][0])
    local_date = local.date()
    week_start = local_date - timedelta(days=local_date.weekday())
    market_close = time(13, 30) if market == "TW" else time(16, 0)
    current_week_confirmed = (
        local.weekday() == 4 and local.time() >= market_close
        and not normalized.empty and normalized.index[-1].date() == local_date
    )
    eligible = normalized if current_week_confirmed else normalized.loc[
        pd.Index(normalized.index.date) < week_start
    ]
    weekly = indicators.to_weekly(eligible)
    if weekly.empty:
        raise ValueError("Kalman 缺少已確認周線資料")
    return weekly


def fetch_weekly_signal(stock: Stock, q: Quote, now: datetime) -> WeeklySignal:
    df = fetch_price_history(stock, "5y")
    if df is None:
        return WeeklySignal(False, "無數據", "無數據：無法取得指標歷史資料")
    try:
        data = indicators.normalize_ohlcv(df)
        if len(data) < 2 or data.index.hasnans or data.index.has_duplicates:
            raise ValueError("歷史資料不足或時間索引異常")
        local_today = now.astimezone(MARKETS[stock.market][0]).date()
        latest_history_date = data.index[-1].date()
        if (latest_history_date > local_today
                or (data.index.date > local_today).any()
                or local_today - latest_history_date > HISTORY_MAX_AGE):
            raise ValueError("指標歷史資料過期或包含未來日期")
        if q.as_of.astimezone(MARKETS[stock.market][0]).date() != local_today:
            raise ValueError("分鐘報價日期不是市場當地今天")
        kalman_input = build_kalman_input(data, q.as_of, stock.market)
        return evaluate_weekly_signal(
            data, current_price=q.price, kalman_input=kalman_input
        )
    except (ValueError, KeyError, TypeError, OverflowError, FloatingPointError) as exc:
        log.warning("[%s] 周線指標無數據: %s", stock.symbol, exc)
        return WeeklySignal(False, "無數據", f"無數據：{exc}")


# ---------- 主流程 ----------

def format_alert(stock: Stock, q: Quote) -> str:
    return f"{stock.symbol} {stock.name}\n現價 {q.price:.2f}"


def append_history(now: datetime, lines: list[str]) -> None:
    HISTORY.mkdir(parents=True, exist_ok=True)
    local = now.astimezone(TPE)
    path = HISTORY / f"{local:%Y%m%d}.md"
    header = "" if path.exists() else f"# {local:%Y-%m-%d} 盯盤紀錄\n"
    with path.open("a", encoding="utf-8") as f:
        f.write(header + f"\n## {local:%H:%M:%S}\n" + "\n".join(f"- {l}" for l in lines) + "\n")


def watchlist_failure_path() -> Path:
    return CACHE / "watchlist_failures.json"


def load_watchlist_failures() -> dict[str, int]:
    path = watchlist_failure_path()
    try:
        with FileLock(str(path.with_suffix(".json.lock")), timeout=10):
            if not path.exists():
                return {}
            data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, Timeout, json.JSONDecodeError) as exc:
        log.error("無法讀取自動移除計數 %s：%s；本次不自動移除標的", path, exc)
        return {}

    if not isinstance(data, dict) or any(
        not isinstance(symbol, str)
        or not isinstance(count, int)
        or isinstance(count, bool)
        or count < 1
        for symbol, count in data.items()
    ):
        log.error("自動移除計數檔格式錯誤：%s；本次不自動移除標的", path)
        return {}
    return {symbol.upper(): count for symbol, count in data.items()}


def save_watchlist_failures(failures: dict[str, int]) -> bool:
    path = watchlist_failure_path()
    temporary_path: str | None = None
    try:
        with FileLock(str(path.with_suffix(".json.lock")), timeout=10):
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, temporary_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as file:
                json.dump(failures, file, ensure_ascii=False, indent=2, sort_keys=True)
            os.replace(temporary_path, path)
            temporary_path = None
        return True
    except (OSError, Timeout) as exc:
        log.error("無法儲存自動移除計數 %s：%s", path, exc)
        return False
    finally:
        if temporary_path is not None:
            try:
                os.unlink(temporary_path)
            except FileNotFoundError:
                pass
            except OSError as exc:
                log.warning("無法清除暫存計數檔 %s：%s", temporary_path, exc)


def prune_history(now: datetime) -> None:
    cutoff = now.astimezone(TPE).date() - timedelta(days=HISTORY_RETENTION_DAYS)
    try:
        entries = list(HISTORY.iterdir())
    except OSError as exc:
        log.warning("無法清理歷史紀錄目錄 %s: %s", HISTORY, exc)
        return

    for path in entries:
        match = re.fullmatch(r"(\d{8})\.md", path.name)
        if match is None or not path.is_file():
            continue
        try:
            history_date = datetime.strptime(match.group(1), "%Y%m%d").date()
        except ValueError:
            continue
        if history_date >= cutoff:
            continue
        try:
            path.unlink()
            log.info("已清理超過 %d 天的歷史紀錄: %s",
                     HISTORY_RETENTION_DAYS, path.name)
        except OSError as exc:
            log.warning("無法刪除過期歷史紀錄 %s: %s", path, exc)


def run_once(args: argparse.Namespace, now: datetime,
             scheduled_at: datetime | None = None) -> int:
    rules = load_rules()

    if not args.force and not should_run(now, rules.run_interval_minutes, args.market):
        log.info("距上次執行未滿 %d 分鐘，略過", rules.run_interval_minutes)
        return 0

    markets = [
        market for market in MARKETS
        if (args.market is None or args.market == market)
        and (not rules.market_hours_only or args.all_markets
             or is_monitoring_window(market, scheduled_at or now))
    ]
    if not markets:
        log.info("目前沒有處於監控時段的市場")
        return 0

    sources = [source for source in tv_screener.load_sources() if source.market in markets]
    records: list[str] = []
    try:
        records.extend(tv_sell_monitor.check_watchlist(
            now, cooldown_minutes=rules.cooldown_minutes, dry_run=args.dry_run
        ))
    except (tv_mcp.TVMCPError, tv_mcp.tv_auth.TVAuthError, OSError, ValueError) as exc:
        message = f"TradingView「{tv_sell_monitor.WATCHLIST_NAME}」週線監控無數據：{exc}"
        log.error(message)
        records.append(message)

    try:
        if any(not any(source.market == market for source in sources) for market in markets):
            raise tv_screener.TVNoData("指定市場沒有設定 TradingView 來源")
        rows = tv_screener.update_watchlist(sources=sources, require_all=True)
        if rows is None:
            raise tv_screener.TVNoData("所有 TradingView 來源都無數據")
    except (tv_screener.TVNoData, OSError) as exc:
        log.error("無數據：更新 watchlist 失敗，本次停止監控：%s", exc)
        append_history(now, records + [
            f"市場 {','.join(markets)}｜無數據：清單更新失敗，"
            f"不使用舊清單取價或通知｜原因：{exc}"
        ])
        mark_run(now, args.market)
        return 1
    records.append(
        f"市場 {','.join(markets)}｜清單更新成功｜來源 "
        f"{','.join(source.key for source in sources)}"
        f"｜更新後該市場標的 {sum(row.market in markets for row in rows)} 檔"
    )
    watchlist = load_watchlist()
    stocks = [s for s in watchlist if args.market is None or s.market == args.market]
    if rules.market_hours_only and not args.all_markets:
        stocks = [s for s in stocks if is_monitoring_window(s.market, scheduled_at or now)]
    if not stocks:
        if watchlist:
            log.info("清單更新後沒有符合本次市場的標的")
            append_history(now, records + ["本次市場清單為空，不取價或通知"])
            mark_run(now, args.market)
            return 0
        log.info("目前沒有可監控標的（watchlist 為空）")
        append_history(now, records + ["本次無可監控標的（市場未開盤或 watchlist 為空）"])
        mark_run(now, args.market)
        return 0

    mcp_client: tv_mcp.TVMCPClient | None = None
    failure_counts = load_watchlist_failures()
    passing: list[tuple[Stock, Quote, WeeklySignal]] = []
    for s in stocks:
        if notifier.is_market_opening_cooloff(s.market, now):
            records.append(f"**{s.symbol} {s.name}**｜原因：{s.market} 開盤冷卻時段，略過訊號過濾與通知")
            continue
        q = fetch_quote(s, _utc_now())
        if q is None:
            records.append(f"**{s.symbol} {s.name}**｜原因：無數據｜指標：無（Yahoo Finance 報價缺失或資料不可信）")
            continue

        signal = fetch_weekly_signal(s, q, now)
        if not signal.passed:
            tv_sync_status = ""
            if signal.summary != "無數據" and not signal.reason.startswith("無數據"):
                key = s.symbol.upper()
                failure_counts[key] = failure_counts.get(key, 0) + 1
                count_saved = save_watchlist_failures(failure_counts)
                if failure_counts[key] >= WATCHLIST_FAILURE_LIMIT:
                    watchlist_name = "台股Screener" if s.market == "TW" else "美股Screener"
                    try:
                        if not count_saved:
                            raise tv_mcp.TVMCPError("未能保存連續未通過次數，為避免誤刪已略過")
                        if mcp_client is None:
                            mcp_client = tv_mcp.TVMCPClient()
                        removed = mcp_client.remove_symbol_from_watchlist(
                            watchlist_name, s.symbol, s.market
                        )
                        failure_counts.pop(key, None)
                        if not save_watchlist_failures(failure_counts):
                            log.error("[%s] 已從 TradingView 移除，但無法更新移除計數檔", s.symbol)
                        result = (
                            f"已移除（連續未通過 {WATCHLIST_FAILURE_LIMIT} 次）"
                            if removed else "原本不在清單中"
                        )
                        tv_sync_status = f"｜TradingView「{watchlist_name}」{result}"
                    except (tv_mcp.TVMCPError, tv_mcp.tv_auth.TVAuthError) as exc:
                        tv_sync_status = f"｜TradingView「{watchlist_name}」自動移除失敗：{exc}"
                        log.error("%s %s", s.symbol, tv_sync_status)
                elif not count_saved:
                    tv_sync_status = "｜連續未通過次數無法保存，本次不執行自動移除"
                else:
                    tv_sync_status = (
                        f"｜TradingView 自動移除計數 "
                        f"{failure_counts[key]}/{WATCHLIST_FAILURE_LIMIT}"
                    )
            records.append(
                f"**{s.symbol} {s.name}**｜原因：{signal.reason}，不通知"
                f"｜指標：{signal.summary}"
                f"{tv_sync_status}"
                f"｜報價時間 {q.as_of.isoformat()}、來源 Yahoo Finance"
            )
            continue

        failure_key = s.symbol.upper()
        if failure_key in failure_counts:
            failure_counts.pop(failure_key)
            save_watchlist_failures(failure_counts)

        passing.append((s, q, signal))

    if passing:
        statuses = notifier.notify_batch(
            [(s.symbol, format_alert(s, q)) for s, q, _ in passing],
            title=f"本輪訊號通過｜市場 {','.join(markets)}",
            cooldown_minutes=rules.cooldown_minutes,
            now=now,
            dry_run=True if args.dry_run else None,
        )
        for s, q, signal in passing:
            status = statuses.get(s.symbol.upper())
            if status is None:
                raise RuntimeError(f"批次通知未回報標的狀態：{s.symbol}")
            tv_sync_status = ""
            if status == notifier.SENT:
                watchlist_name = "台股Screener" if s.market == "TW" else "美股Screener"
                try:
                    if mcp_client is None:
                        mcp_client = tv_mcp.TVMCPClient()
                    added = mcp_client.add_symbol_to_watchlist(
                        watchlist_name, s.symbol, s.market
                    )
                    result = "已加入" if added else "已存在"
                    tv_sync_status = f"｜TradingView「{watchlist_name}」{result}"
                except (tv_mcp.TVMCPError, tv_mcp.tv_auth.TVAuthError) as exc:
                    tv_sync_status = f"｜TradingView「{watchlist_name}」同步失敗：{exc}"
                    log.error("%s %s", s.symbol, tv_sync_status)
            records.append(
                f"**{s.symbol} {s.name}**｜原因：{signal.reason}，"
                f"｜指標：{signal.summary}"
                f"｜現價 {q.price:.2f}"
                f"｜通知結果 {status}{tv_sync_status}"
                f"｜報價時間 {q.as_of.isoformat()}、來源 Yahoo Finance"
            )

    append_history(now, records)
    mark_run(now, args.market)
    for r in records:
        log.info(r)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="台股 + 美股 盯盤 Agent")
    parser.add_argument("--market", choices=("TW", "US"), help="只監控指定市場")
    parser.add_argument("--force", action="store_true", help="忽略執行間隔節流")
    parser.add_argument("--all-markets", action="store_true", help="忽略開盤時間過濾")
    parser.add_argument("--dry-run", action="store_true", help="不實際推播")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    CACHE.mkdir(parents=True, exist_ok=True)

    scheduled_at = datetime.now(timezone.utc)
    try:
        with FileLock(str(LOCK_FILE), timeout=600 if args.market else 0):
            prune_history(datetime.now(timezone.utc))
            return run_once(args, datetime.now(timezone.utc), scheduled_at=scheduled_at)
    except Timeout:
        log.warning("另一個執行個體正在運行（%s），本次結束", LOCK_FILE)
        return 1 if args.market else 0


if __name__ == "__main__":
    sys.exit(main())
