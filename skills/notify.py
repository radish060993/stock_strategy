"""Telegram 推播 Skill，含同一標的 Cool-down 機制。

環境變數：
    TELEGRAM_BOT_TOKEN  Bot token
    TELEGRAM_CHAT_ID    接收訊息的 chat id

未設定上述變數時自動進入 dry-run：只印出訊息、不送出，也不寫入 cooldown。
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from filelock import FileLock

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env", override=True)
COOLDOWN_FILE = ROOT / "data" / "cache" / "cooldown.json"
COOLDOWN_LOCK = COOLDOWN_FILE.with_suffix(".json.lock")
DEFAULT_COOLDOWN_MINUTES = 30
MARKET_OPENING_COOLOFF = {
    "TW": (ZoneInfo("Asia/Taipei"), time(9, 0), time(9, 20)),
    "US": (ZoneInfo("America/New_York"), time(9, 30), time(10, 0)),
}

SENT = "sent"
COOLDOWN = "cooldown"
DRY_RUN = "dry_run"
FAILED = "failed"
TELEGRAM_MESSAGE_LIMIT = 4096


def _now() -> datetime:
    return datetime.now(timezone.utc)


def is_market_opening_cooloff(market: str, now: datetime | None = None) -> bool:
    """開盤冷卻時段內回傳 True；TW 為 09:00-09:20，US 為 09:30-10:00。"""
    schedule = MARKET_OPENING_COOLOFF.get(market.upper())
    if schedule is None:
        return False
    tz, start, end = schedule
    local = (now or _now()).astimezone(tz)
    return local.weekday() < 5 and start <= local.time() < end


def _load_cooldown() -> dict[str, str]:
    if not COOLDOWN_FILE.exists():
        return {}
    try:
        data = json.loads(COOLDOWN_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("cooldown.json 無法讀取，視為空白: %s", exc)
        return {}


def _save_cooldown(data: dict[str, str]) -> None:
    COOLDOWN_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=COOLDOWN_FILE.parent, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
    os.replace(tmp, COOLDOWN_FILE)


def _last_sent(data: dict[str, str], symbol: str) -> datetime | None:
    raw = data.get(symbol.upper())
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def is_in_cooldown(symbol: str, minutes: int = DEFAULT_COOLDOWN_MINUTES,
                   now: datetime | None = None) -> bool:
    now = now or _now()
    with FileLock(str(COOLDOWN_LOCK), timeout=10):
        last = _last_sent(_load_cooldown(), symbol)
    return last is not None and now - last < timedelta(minutes=minutes)


def send_telegram(text: str, token: str | None = None, chat_id: str | None = None,
                  timeout: float = 10.0) -> bool:
    token = token or os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        raise RuntimeError("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID 未設定")

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    body = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": "true",
    }).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=body), timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
            if not payload.get("ok"):
                log.error("Telegram 回應失敗: %s", payload)
                return False
            return True
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        log.error("Telegram 推播失敗（%s）", type(exc).__name__)
        return False


def notify(symbol: str, text: str, cooldown_minutes: int = DEFAULT_COOLDOWN_MINUTES,
           now: datetime | None = None, dry_run: bool | None = None) -> str:
    """推播單一標的訊息，回傳 SENT / COOLDOWN / DRY_RUN / FAILED。

    只有成功送出才會更新 cooldown，失敗時下次仍會重試。
    """
    now = now or _now()
    key = symbol.upper()
    if dry_run is None:
        dry_run = not (os.getenv("TELEGRAM_BOT_TOKEN") and os.getenv("TELEGRAM_CHAT_ID"))

    with FileLock(str(COOLDOWN_LOCK), timeout=10):
        data = _load_cooldown()
        last = _last_sent(data, key)
        if last is not None and now - last < timedelta(minutes=cooldown_minutes):
            log.info("[%s] cool-down 中（上次 %s），略過", key, last.isoformat())
            return COOLDOWN

        if dry_run:
            print(f"[DRY-RUN] {text}")
            return DRY_RUN

        if not send_telegram(text):
            return FAILED

        data[key] = now.isoformat()
        # 清掉超過一天的舊紀錄，避免檔案無限成長
        cutoff = now - timedelta(days=1)
        data = {k: v for k, v in data.items() if (_last_sent(data, k) or now) >= cutoff}
        _save_cooldown(data)
        return SENT


def _format_batch_messages(title: str, alerts: list[tuple[str, str]]) -> list[str]:
    header = f"{title}｜{len(alerts)} 檔"
    message = header + "\n\n" + "\n\n".join(text for _, text in alerts)
    if len(message) <= TELEGRAM_MESSAGE_LIMIT:
        return [message]

    header_reserve = len(f"{header}（9999/9999）\n\n")
    content_limit = TELEGRAM_MESSAGE_LIMIT - header_reserve
    groups: list[list[tuple[str, str]]] = []
    current: list[tuple[str, str]] = []
    current_length = 0
    for alert in alerts:
        text_length = len(alert[1])
        if text_length > content_limit:
            raise ValueError(
                f"單一標的通知超過 Telegram {TELEGRAM_MESSAGE_LIMIT} 字元限制：{alert[0]}"
            )
        added_length = text_length + (2 if current else 0)
        if current and current_length + added_length > content_limit:
            groups.append(current)
            current = []
            current_length = 0
            added_length = text_length
        current.append(alert)
        current_length += added_length
    if current:
        groups.append(current)

    return [
        f"{header}（{index}/{len(groups)}）\n\n"
        + "\n\n".join(text for _, text in group)
        for index, group in enumerate(groups, start=1)
    ]


def notify_batch(alerts: list[tuple[str, str]], title: str,
                 cooldown_minutes: int = DEFAULT_COOLDOWN_MINUTES,
                 now: datetime | None = None,
                 dry_run: bool | None = None) -> dict[str, str]:
    """Send all non-cooled-down alerts together, keeping cooldown per symbol."""
    if not alerts:
        return {}

    keys = [symbol.strip().upper() for symbol, _ in alerts]
    if any(not key for key in keys) or len(set(keys)) != len(keys):
        raise ValueError("批次通知的標的代號必須非空且不可重複")

    now = now or _now()
    if dry_run is None:
        dry_run = not (os.getenv("TELEGRAM_BOT_TOKEN") and os.getenv("TELEGRAM_CHAT_ID"))

    with FileLock(str(COOLDOWN_LOCK), timeout=10):
        data = _load_cooldown()
        statuses: dict[str, str] = {}
        eligible: list[tuple[str, str]] = []
        eligible_keys: list[str] = []
        for alert, key in zip(alerts, keys):
            last = _last_sent(data, key)
            if last is not None and now - last < timedelta(minutes=cooldown_minutes):
                statuses[key] = COOLDOWN
            else:
                eligible.append(alert)
                eligible_keys.append(key)
        if not eligible:
            return statuses

        try:
            messages = _format_batch_messages(title, eligible)
        except ValueError as exc:
            log.error("無法建立批次 Telegram 通知：%s", exc)
            statuses.update({key: FAILED for key in eligible_keys})
            return statuses
        if dry_run:
            for message in messages:
                print(f"[DRY-RUN] {message}")
            for key in eligible_keys:
                statuses[key] = DRY_RUN
            return statuses

        for message in messages:
            if not send_telegram(message):
                statuses.update({key: FAILED for key in eligible_keys})
                return statuses

        for key in eligible_keys:
            statuses[key] = SENT
            data[key] = now.isoformat()
        cutoff = now - timedelta(days=1)
        data = {k: v for k, v in data.items() if (_last_sent(data, k) or now) >= cutoff}
        _save_cooldown(data)
        return statuses


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO)
    if len(sys.argv) > 1 and sys.argv[1] == "--test":
        msg = sys.argv[2] if len(sys.argv) > 2 else "Telegram connection test"
        try:
            success = send_telegram(msg)
        except RuntimeError as exc:
            print(f"Telegram test failed: {exc}", file=sys.stderr)
            sys.exit(2)
        print("Telegram test sent" if success else "Telegram test failed")
        sys.exit(0 if success else 1)

    sym = sys.argv[1] if len(sys.argv) > 1 else "TEST"
    msg = sys.argv[2] if len(sys.argv) > 2 else f"{sym} 測試訊息"
    status = notify(sym, msg)
    print(status)
    sys.exit(1 if status == FAILED else 0)
