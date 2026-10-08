import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from skills import notify


class BatchNotifyTests(unittest.TestCase):
    def test_batches_alerts_and_applies_cooldown_per_symbol(self):
        now = datetime(2026, 10, 7, 1, tzinfo=timezone.utc)
        alerts = [
            ("2330.TW", "2330.TW 台積電\n現價 1000.00"),
            ("2317.TW", "2317.TW 鴻海\n現價 200.00"),
        ]
        with tempfile.TemporaryDirectory() as directory:
            cooldown_file = Path(directory) / "cooldown.json"
            with patch.object(notify, "COOLDOWN_FILE", cooldown_file), \
                    patch.object(notify, "COOLDOWN_LOCK",
                                 cooldown_file.with_suffix(".json.lock")), \
                    patch.object(notify, "send_telegram", return_value=True) as send:
                statuses = notify.notify_batch(
                    alerts, "本輪訊號通過｜市場 TW", now=now, dry_run=False
                )

                self.assertEqual(statuses, {
                    "2330.TW": notify.SENT,
                    "2317.TW": notify.SENT,
                })
                send.assert_called_once()
                self.assertIn("本輪訊號通過｜市場 TW｜2 檔", send.call_args.args[0])
                self.assertIn("2330.TW 台積電", send.call_args.args[0])
                self.assertIn("2317.TW 鴻海", send.call_args.args[0])

                statuses = notify.notify_batch(
                    alerts + [("2454.TW", "2454.TW 聯發科\n現價 1500.00")],
                    "本輪訊號通過｜市場 TW",
                    now=now + timedelta(minutes=10),
                    dry_run=False,
                )

                self.assertEqual(statuses, {
                    "2330.TW": notify.COOLDOWN,
                    "2317.TW": notify.COOLDOWN,
                    "2454.TW": notify.SENT,
                })
                self.assertEqual(send.call_count, 2)
                self.assertIn("2454.TW 聯發科", send.call_args.args[0])
                cooldowns = json.loads(cooldown_file.read_text(encoding="utf-8"))
                self.assertEqual(set(cooldowns), {"2330.TW", "2317.TW", "2454.TW"})

    def test_splits_only_when_telegram_message_limit_requires_it(self):
        alerts = [
            (f"STOCK{i}", f"STOCK{i} " + "x" * 2500)
            for i in range(2)
        ]
        with tempfile.TemporaryDirectory() as directory:
            cooldown_file = Path(directory) / "cooldown.json"
            with patch.object(notify, "COOLDOWN_FILE", cooldown_file), \
                    patch.object(notify, "COOLDOWN_LOCK",
                                 cooldown_file.with_suffix(".json.lock")), \
                    patch.object(notify, "send_telegram", return_value=True) as send:
                statuses = notify.notify_batch(
                    alerts,
                    "本輪訊號通過",
                    now=datetime(2026, 10, 7, 1, tzinfo=timezone.utc),
                    dry_run=False,
                )

        self.assertEqual(set(statuses.values()), {notify.SENT})
        self.assertEqual(send.call_count, 2)
        for call in send.call_args_list:
            self.assertLessEqual(len(call.args[0]), notify.TELEGRAM_MESSAGE_LIMIT)
            self.assertIn("/2）", call.args[0])


if __name__ == "__main__":
    unittest.main()
