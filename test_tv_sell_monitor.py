import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from skills import tv_mcp, tv_sell_monitor


class WeeklyVolumeMonitorTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 6, 12, tzinfo=timezone.utc)
        self.bar_time = int((self.now - timedelta(minutes=30)).timestamp())
        self.client = Mock()
        self.client.list_watchlists.return_value = [{
            "name": tv_sell_monitor.WATCHLIST_NAME,
            "symbols": ["NASDAQ:INTC"],
        }]
        self.client.call_tool.return_value = {
            "bars": [{"t": self.bar_time, "o": 100.0, "c": 99.0}]
        }
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.state_file = Path(self.temp_dir.name) / "states.json"
        self.patches = (
            patch.object(tv_sell_monitor, "STATE_FILE", self.state_file),
            patch.object(tv_sell_monitor.tv_mcp, "TVMCPClient",
                         return_value=self.client),
            patch.object(tv_sell_monitor.notify, "notify",
                         return_value=tv_sell_monitor.notify.SENT),
        )
        self.mocks = [item.start() for item in self.patches]
        for item in self.patches:
            self.addCleanup(item.stop)
        self.notify = self.mocks[2]

    def test_first_observation_baselines_without_alerting_even_if_red(self):
        records = tv_sell_monitor.check_watchlist(self.now)

        self.notify.assert_not_called()
        self.assertIn("週線成交量柱 紅色", records[0])
        states = json.loads(self.state_file.read_text(encoding="utf-8"))
        self.assertEqual(states["NASDAQ:INTC"]["red"], True)
        self.client.call_tool.assert_called_once_with(
            "mcp-tv-get-ohlcv",
            {"symbol": "NASDAQ:INTC", "interval": "1W", "count": 2},
        )

    def test_green_to_red_transition_sends_factual_notification(self):
        previous_bar_time = self.bar_time - 7 * 24 * 60 * 60
        self.state_file.write_text(json.dumps({
            "NASDAQ:INTC": {"bar_time": previous_bar_time, "red": False}
        }), encoding="utf-8")

        records = tv_sell_monitor.check_watchlist(self.now)

        self.notify.assert_called_once()
        message = self.notify.call_args.args[1]
        self.assertIn("週線成交量柱轉紅", message)
        self.assertNotIn("要賣出", message)
        self.assertIn("週線成交量柱由綠轉紅", records[0])
        self.assertEqual(
            json.loads(self.state_file.read_text(encoding="utf-8"))["NASDAQ:INTC"]["red"],
            True,
        )

    def test_dry_run_does_not_consume_a_red_transition(self):
        self.state_file.write_text(json.dumps({
            "NASDAQ:INTC": {"bar_time": self.bar_time - 60, "red": False}
        }), encoding="utf-8")
        self.notify.return_value = tv_sell_monitor.notify.DRY_RUN

        tv_sell_monitor.check_watchlist(self.now, dry_run=True)

        self.assertFalse(
            json.loads(self.state_file.read_text(encoding="utf-8"))["NASDAQ:INTC"]["red"]
        )

    def test_same_red_state_does_not_repeat_notification(self):
        self.state_file.write_text(json.dumps({
            "NASDAQ:INTC": {"bar_time": self.bar_time - 60, "red": True}
        }), encoding="utf-8")

        records = tv_sell_monitor.check_watchlist(self.now)

        self.notify.assert_not_called()
        self.assertIn("週線成交量柱 紅色", records[0])

    def test_stale_weekly_bar_is_reported_as_no_data(self):
        self.client.call_tool.return_value = {
            "bars": [{"t": self.bar_time - 8 * 24 * 60 * 60, "o": 100, "c": 99}]
        }

        records = tv_sell_monitor.check_watchlist(self.now)

        self.notify.assert_not_called()
        self.assertIn("無數據", records[0])
        self.assertFalse(self.state_file.exists())

    def test_missing_or_duplicate_named_watchlist_is_an_error(self):
        self.client.list_watchlists.return_value = [
            {"name": tv_sell_monitor.WATCHLIST_NAME, "symbols": []},
            {"name": tv_sell_monitor.WATCHLIST_NAME, "symbols": []},
        ]

        with self.assertRaises(tv_mcp.TVMCPError):
            tv_sell_monitor.check_watchlist(self.now)

        self.client.call_tool.assert_not_called()
        self.notify.assert_not_called()

    def test_market_opening_cooloff_skips_weekly_query(self):
        self.now = datetime(2026, 10, 6, 1, 5, tzinfo=timezone.utc)
        self.client.list_watchlists.return_value[0]["symbols"] = ["TWSE:2330"]

        records = tv_sell_monitor.check_watchlist(self.now)

        self.client.call_tool.assert_not_called()
        self.notify.assert_not_called()
        self.assertIn("開盤冷卻時段", records[0])


if __name__ == "__main__":
    unittest.main()
