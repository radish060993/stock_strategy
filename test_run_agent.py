import argparse
import itertools
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

import run_agent as agent


class HistoryRetentionTests(unittest.TestCase):
    def test_prunes_only_daily_markdown_older_than_retention(self):
        now = datetime(2026, 10, 5, 3, tzinfo=timezone.utc)
        cutoff = now.astimezone(agent.TPE).date() - timedelta(
            days=agent.HISTORY_RETENTION_DAYS
        )
        with tempfile.TemporaryDirectory() as directory:
            history = Path(directory)
            old_file = history / (cutoff - timedelta(days=1)).strftime("%Y%m%d.md")
            boundary_file = history / cutoff.strftime("%Y%m%d.md")
            malformed_file = history / "20260230.md"
            unrelated_file = history / "notes.md"
            old_file.touch()
            boundary_file.touch()
            malformed_file.touch()
            unrelated_file.touch()
            (history / "20260101").mkdir()

            with patch.object(agent, "HISTORY", history):
                agent.prune_history(now)

            self.assertFalse(old_file.exists())
            self.assertTrue(boundary_file.exists())
            self.assertTrue(malformed_file.exists())
            self.assertTrue(unrelated_file.exists())
            self.assertTrue((history / "20260101").is_dir())


class AlertFormatTests(unittest.TestCase):
    def test_alert_contains_only_symbol_name_and_price(self):
        stock = agent.Stock("2330.TW", "TW", "台積電")
        quote = agent.Quote(
            1234.5, datetime(2026, 10, 5, 3, tzinfo=timezone.utc)
        )

        self.assertEqual(
            agent.format_alert(stock, quote),
            "2330.TW 台積電\n現價 1234.50",
        )


class TradingViewWatchlistSyncTests(unittest.TestCase):
    def test_taiwan_ticker_is_converted_and_added_idempotently(self):
        client = agent.tv_mcp.TVMCPClient(access_token="test-token")
        watchlist = {"id": 123, "name": "台股Screener", "symbols": []}
        with patch.object(client, "list_watchlists", return_value=[watchlist]), \
                patch.object(client, "call_tool", return_value={
                    "watchlist_id": "123", "symbols": ["TPEX:6274"]
                }) as call_tool:
            self.assertTrue(client.add_symbol_to_watchlist(
                "台股Screener", "6274.TWO", "TW"
            ))
            call_tool.assert_called_once_with(
                "mcp-watchlist-add-to-watchlist",
                {"watchlist_id": "123", "symbols": ["TPEX:6274"]},
            )

        watchlist["symbols"] = ["TPEX:6274"]
        with patch.object(client, "list_watchlists", return_value=[watchlist]), \
                patch.object(client, "call_tool") as call_tool:
            self.assertFalse(client.add_symbol_to_watchlist(
                "台股Screener", "6274.TWO", "TW"
            ))
            call_tool.assert_not_called()

    def test_us_ticker_uses_tradingview_primary_us_listing(self):
        client = agent.tv_mcp.TVMCPClient(access_token="test-token")
        candidates = [
            {"symbol": "BOATS:AAPL", "exchange": "BOATS",
             "currency_logoid": "country/US", "type": "stock"},
            {"symbol": "NASDAQ:AAPL", "exchange": "NASDAQ",
             "currency_logoid": "country/US", "type": "stock"},
        ]

        def call_tool(name, arguments):
            if name == "mcp-tv-search-symbols":
                self.assertEqual(arguments["query"], "AAPL")
                return {"data": {"symbols": candidates}, "success": True}
            return {"watchlist_id": "456", "symbols": ["NASDAQ:AAPL"]}

        with patch.object(client, "list_watchlists", return_value=[
            {"id": 456, "name": "美股Screener", "symbols": []}
        ]), patch.object(client, "call_tool", side_effect=call_tool) as tool:
            self.assertTrue(client.add_symbol_to_watchlist(
                "美股Screener", "AAPL", "US"
            ))

        self.assertEqual(
            [entry.args[0] for entry in tool.call_args_list],
            ["mcp-tv-search-symbols", "mcp-watchlist-add-to-watchlist"],
        )

    def test_tsm_uses_nyse_and_ignores_pyth_feed_candidate(self):
        client = agent.tv_mcp.TVMCPClient(access_token="test-token")
        candidates = [
            {"symbol": "PYTH:TSM", "exchange": "PYTH",
             "currency_logoid": "country/US", "type": "dr"},
            {"symbol": "NYSE:TSM", "exchange": "NYSE",
             "currency_logoid": "country/US", "type": "dr"},
        ]
        with patch.object(client, "call_tool", return_value={
            "data": {"symbols": candidates},
        }):
            self.assertEqual(client._resolve_watchlist_symbol("TSM", "US"), "NYSE:TSM")

    def test_tsm_rejects_pyth_when_nyse_listing_is_missing(self):
        client = agent.tv_mcp.TVMCPClient(access_token="test-token")
        with patch.object(client, "call_tool", return_value={
            "data": {"symbols": [
                {"symbol": "PYTH:TSM", "exchange": "PYTH",
                 "currency_logoid": "country/US", "type": "dr"},
            ]},
        }):
            with self.assertRaisesRegex(agent.tv_mcp.TVMCPError, "有效美股交易所"):
                client._resolve_watchlist_symbol("TSM", "US")

    def test_removes_symbol_from_watchlist_and_verifies_result(self):
        client = agent.tv_mcp.TVMCPClient(access_token="test-token")
        watchlist = {"id": 123, "name": "台股Screener", "symbols": ["TPEX:6274"]}
        with patch.object(client, "list_watchlists", return_value=[watchlist]), \
                patch.object(client, "_resolve_watchlist_symbol", return_value="TPEX:6274"), \
                patch.object(client, "call_tool", return_value={
                    "watchlist_id": "123", "symbols": []
                }) as call_tool:
            self.assertTrue(client.remove_symbol_from_watchlist(
                "台股Screener", "6274.TWO", "TW"
            ))
        call_tool.assert_called_once_with(
            "mcp-watchlist-remove-from-watchlist",
            {"watchlist_id": "123", "symbols": ["TPEX:6274"]},
        )
        self.assertEqual(watchlist["symbols"], [])

    def test_does_not_call_remove_for_symbol_not_in_watchlist(self):
        client = agent.tv_mcp.TVMCPClient(access_token="test-token")
        watchlist = {"id": 123, "name": "台股Screener", "symbols": []}
        with patch.object(client, "list_watchlists", return_value=[watchlist]), \
                patch.object(client, "_resolve_watchlist_symbol", return_value="TPEX:6274"), \
                patch.object(client, "call_tool") as call_tool:
            self.assertFalse(client.remove_symbol_from_watchlist(
                "台股Screener", "6274.TWO", "TW"
            ))
        call_tool.assert_not_called()


def weekly_history(periods: int = 100) -> pd.DataFrame:
    close = np.linspace(100.0, 500.0, periods)
    df = pd.DataFrame(
        {"Open": close - 1, "High": close + 2, "Low": close - 2,
         "Close": close, "Volume": 1000.0},
        index=pd.date_range(end="2026-10-02", periods=periods, freq="W-FRI",
                            tz="Asia/Taipei"),
    )
    df.iloc[6, df.columns.get_loc("High")] = max(220.0, df["High"].iloc[6])
    return df


class WeeklySignalTests(unittest.TestCase):
    def setUp(self):
        self.data = weekly_history()

    def evaluate_colors(self, darvas_color, squeeze_color, kalman_color, strength,
                        current_price=None, kalman_line=490.0, data=None):
        darvas = pd.DataFrame({"top": [520.0], "bottom": [480.0], "color": [darvas_color]})
        squeeze = pd.DataFrame({"val": [1.0, 2.0], "color": [squeeze_color, squeeze_color]})
        kalman = pd.DataFrame(
            {"kalman": [kalman_line], "trend_strength": [strength], "oscillator": [20.0],
             "color": [kalman_color]}
        )
        with patch.object(agent.indicators, "darvas_box_series", return_value=darvas), \
                patch.object(agent.indicators, "squeeze_momentum_series", return_value=squeeze), \
                patch.object(agent.indicators, "kalman_trend_series", return_value=kalman):
            return agent.evaluate_weekly_signal(
                self.data if data is None else data, current_price=current_price
            )

    def test_color_truth_table(self):
        for darvas, squeeze, kalman in itertools.product(
                ("green", "yellow", "red"), ("lime", "green", "maroon", "red"),
                ("green", "red", "blue")):
            with self.subTest(darvas=darvas, squeeze=squeeze, kalman=kalman):
                strength = {"green": 10.0, "red": -10.0, "blue": 0.0}[kalman]
                signal = self.evaluate_colors(darvas, squeeze, kalman, strength)
                expected = darvas != "red" and squeeze != "red" and strength >= -10
                self.assertEqual(signal.passed, expected)
                if not expected:
                    self.assertIn("未通過", signal.reason)

    def test_kalman_exact_threshold(self):
        for strength, color in itertools.product(
                (-10.001, -10.0, -9.999, -0.001, 0.0, 0.001, 1.0, 9.999,
                 10.0, 10.001),
                ("blue", "green", "red")):
            with self.subTest(strength=strength, color=color):
                signal = self.evaluate_colors("yellow", "maroon", color, strength)
                self.assertEqual(signal.passed, strength >= -10)
                if strength < -10:
                    self.assertIn("Kalman 趨勢強度 >= -10", signal.reason)

    def test_reported_four_stocks_fail_kalman_gates(self):
        for symbol, price, line, strength, reason in (
                ("TSM", 483.0, 445.0, 31.0, "現價與 Kalman line 價差 < 7%"),
                ("MDB", 362.0, 384.0, 4.0, "當前價 > Kalman line"),
                ("CNC", 64.0, 64.4, -8.0, "當前價 > Kalman line"),
                ("NEM", 116.0, 121.0, 20.0, "當前價 > Kalman line")):
            with self.subTest(symbol=symbol):
                signal = self.evaluate_colors(
                    "green", "lime", "blue", strength,
                    current_price=price, kalman_line=line,
                )
                self.assertFalse(signal.passed)
                self.assertIn(reason, signal.reason)

    def test_kalman_price_line_matches_pine_per_bar_diagonal_reset(self):
        data = pd.DataFrame(
            {
                "Open": [99.0, 109.0, 104.0, 107.0],
                "High": [101.0, 111.0, 106.0, 109.0],
                "Low": [98.0, 108.0, 103.0, 106.0],
                "Close": [100.0, 110.0, 105.0, 108.0],
                "Volume": [1000.0] * 4,
            },
            index=pd.date_range(
                "2026-01-02", periods=4, freq="W-FRI", tz="Asia/Taipei"
            ),
        )

        result = agent.indicators.kalman_trend_series(data)

        np.testing.assert_allclose(
            result["kalman"].to_numpy(),
            [199.599609569530, 198.690477896338,
             197.234978144988, 195.305650877581],
            rtol=1e-11,
        )

    def test_current_quote_must_be_above_kalman_line(self):
        close = float(self.data["Close"].iloc[-1])
        for kalman_line, passed in ((close - 0.01, True), (close, False),
                                    (close + 0.01, False)):
            with self.subTest(kalman_line=kalman_line):
                signal = self.evaluate_colors(
                    "green", "lime", "blue", 0.0, kalman_line=kalman_line
                )
                self.assertEqual(signal.passed, passed)
                if not passed:
                    self.assertIn("當前價 > Kalman line", signal.reason)

        below_line = self.evaluate_colors(
            "green", "lime", "blue", 0.0,
            current_price=close - 1, kalman_line=close - 0.5,
        )
        self.assertFalse(below_line.passed)
        self.assertIn("當前價 > Kalman line", below_line.reason)

    def test_current_price_kalman_gap_must_be_below_seven_percent(self):
        for current_price, kalman_line, passed in (
                (106.999, 100.0, True), (107.0, 100.0, False),
                (108.0, 100.0, False), (90.0, 85.0, True)):
            with self.subTest(current_price=current_price):
                signal = self.evaluate_colors(
                    "green", "lime", "green", 10.0,
                    current_price=current_price, kalman_line=kalman_line,
                )
                self.assertEqual(signal.passed, passed)
                if not passed:
                    self.assertIn("現價與 Kalman line 價差 < 7%", signal.reason)

    def test_unknown_colors_fail_closed(self):
        for colors in ((None, "green", "green"), ("green", None, "green"),
                       ("green", "green", None), ("purple", "green", "green")):
            with self.subTest(colors=colors), self.assertRaisesRegex(ValueError, "顏色未知"):
                self.evaluate_colors(*colors, 10.0)

    def test_nonfinite_indicator_fails_closed(self):
        for strength in (np.nan, np.inf, -np.inf):
            with self.subTest(strength=strength), self.assertRaisesRegex(ValueError, "有效數值"):
                self.evaluate_colors("green", "green", "green", strength)

    def test_real_series_pass(self):
        signal = agent.evaluate_weekly_signal(self.data, current_price=500.0)
        self.assertTrue(signal.passed)
        for text in ("Darvas green", "Squeeze", "Kalman green", "未收完當週"):
            self.assertIn(text, signal.summary)

    def test_real_series_blocks_price_gap_over_seven_percent(self):
        signal = agent.evaluate_weekly_signal(self.data, current_price=600.0)
        self.assertFalse(signal.passed)
        self.assertEqual(signal.reason, "未通過：現價與 Kalman line 價差 < 7%")
        self.assertIn("價差 22.24%", signal.summary)

    def test_confirmed_kalman_is_independent_of_current_quote(self):
        original = self.data.copy(deep=True)
        lines = []
        real_kalman_series = agent.indicators.kalman_trend_series
        with patch.object(agent.indicators, "kalman_trend_series",
                          wraps=real_kalman_series) as kalman:
            for price in (500.0, 510.0):
                signal = agent.evaluate_weekly_signal(
                    self.data, current_price=price, kalman_input=self.data
                )
                expected = original.copy(deep=True)
                pd.testing.assert_frame_equal(kalman.call_args.args[0], expected)
                self.assertEqual(kalman.call_args.kwargs, {
                    "measurement_noise": 30.0, "osc_smooth": 5,
                    "trend_lookback": 20, "strength_smooth": 10, "model": "standard",
                })
                last = real_kalman_series(expected, **kalman.call_args.kwargs).iloc[-1]
                self.assertIn(f"Kalman line {last['kalman']:.2f}", signal.summary)
                self.assertIn("已確認周 K", signal.summary)
                lines.append(float(last["kalman"]))
        self.assertEqual(lines[0], lines[1])
        pd.testing.assert_frame_equal(self.data, original)

    def test_darvas_exact_box_boundaries(self):
        box = agent.indicators.darvas_box_series(self.data).iloc[-1]
        for price, color, passed in (
                (box["bottom"] - 0.01, "red", False),
                (box["bottom"], "yellow", True),
                (box["top"], "yellow", True),
                (box["top"] + 0.01, "green", True)):
            data = self.data.copy()
            data.loc[data.index[-1], ["Open", "Close", "Low"]] = [price, price, price - 1]
            squeeze = pd.DataFrame({"val": [1.0, 2.0], "color": ["lime", "lime"]})
            kalman = pd.DataFrame(
                {"kalman": [price / 1.05], "trend_strength": [10.0], "oscillator": [10.0],
                 "color": ["green"]}
            )
            with self.subTest(price=price), \
                    patch.object(agent.indicators, "squeeze_momentum_series",
                                 return_value=squeeze), \
                    patch.object(agent.indicators, "kalman_trend_series",
                                 return_value=kalman), \
                    patch.object(agent.indicators, "calculate_weekly_filters",
                                 return_value=agent.indicators.calculate_weekly_filters(self.data)):
                signal = agent.evaluate_weekly_signal(data)
                self.assertEqual(signal.passed, passed)
                self.assertIn(f"Darvas {color}", signal.summary)

    def test_each_weekly_filter_blocks_signal(self):
        names = {
            "ma_trend": "周線 MA10 > MA20",
            "doji": "周線實體幅度 <= 8%",
            "volume_green": "前 6 週至少 3 週綠色量柱",
            "not_consecutive_red_volume": "本週與上週不可連續紅色量柱",
        }
        for key, name in names.items():
            filters = agent.indicators.calculate_weekly_filters(self.data)
            filters["checks"][key] = False
            filters["passed"] = False
            with self.subTest(key=key), \
                    patch.object(agent.indicators, "calculate_weekly_filters",
                                 return_value=filters):
                signal = agent.evaluate_weekly_signal(self.data)
                self.assertFalse(signal.passed)
                self.assertIn(name, signal.reason)
                self.assertIn("周線過濾 未通過", signal.summary)

    def test_real_weekly_filter_failures(self):
        doji = self.data.copy()
        doji.at[doji.index[-1], "Open"] = 400.0
        doji.at[doji.index[-1], "Low"] = 399.0
        green_volume = self.data.copy()
        green_volume.loc[green_volume.index[-7:-1], "Open"] = (
            green_volume["Close"].iloc[-7:-1] + 1
        )
        for data, reason in ((doji, "周線實體幅度"),
                             (green_volume, "綠色量柱")):
            with self.subTest(reason=reason):
                signal = agent.evaluate_weekly_signal(data)
                self.assertFalse(signal.passed)
                self.assertIn(reason, signal.reason)

    def test_common_weekly_overlap_does_not_block_signal(self):
        for weeks in (4, 5, 10):
            data = self.data.copy()
            data.loc[data.index[-weeks:], "Low"] = 450.0
            common_low = data["Low"].tail(weeks).max()
            common_high = data["High"].tail(weeks).min()
            with self.subTest(weeks=weeks):
                self.assertLessEqual(common_low, common_high)
                filters = agent.indicators.calculate_weekly_filters(data)
                self.assertTrue(filters["passed"])
                self.assertEqual(set(filters["checks"]), {
                    "ma_trend", "doji", "volume_green",
                    "not_consecutive_red_volume",
                })
                self.assertNotIn("overlap_weeks", filters)
                signal = agent.evaluate_weekly_signal(data)
                self.assertTrue(signal.passed)
                self.assertIn("周線過濾 通過", signal.summary)
                self.assertNotIn("重疊", signal.reason)
                self.assertNotIn("重疊", signal.summary)

    def test_weekly_filter_allows_single_red_volume_bar_but_not_two(self):
        one_red = self.data.copy()
        one_red.loc[one_red.index[-1], "Open"] = (
            one_red["Close"].iloc[-1] + 1
        )
        filters = agent.indicators.calculate_weekly_filters(one_red)
        self.assertTrue(filters["checks"]["not_consecutive_red_volume"])
        self.assertTrue(filters["passed"])

        two_red = one_red.copy()
        two_red.loc[two_red.index[-2], "Open"] = (
            two_red["Close"].iloc[-2] + 1
        )
        filters = agent.indicators.calculate_weekly_filters(two_red)
        self.assertFalse(filters["checks"]["not_consecutive_red_volume"])
        self.assertFalse(filters["passed"])

        previous_red_only = self.data.copy()
        previous_red_only.loc[previous_red_only.index[-2], "Open"] = (
            previous_red_only["Close"].iloc[-2] + 1
        )
        filters = agent.indicators.calculate_weekly_filters(previous_red_only)
        self.assertTrue(filters["checks"]["not_consecutive_red_volume"])

    def test_bad_or_missing_volume_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "Volume"):
            agent.evaluate_weekly_signal(self.data.drop(columns="Volume"))
        for value in (np.nan, np.inf, -np.inf, -1.0):
            data = self.data.copy()
            data.at[data.index[20], "Volume"] = value
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "Volume"):
                agent.evaluate_weekly_signal(data)

    def test_unformed_box_is_not_nonred(self):
        data = self.data.copy()
        data["High"] = data["Close"] + 2
        with self.assertRaisesRegex(ValueError, "Box"):
            agent.evaluate_weekly_signal(data)

    def test_short_history_uses_indicator_validity(self):
        for count in (1, 20, 38):
            with self.subTest(count=count), self.assertRaisesRegex(
                    ValueError, "指標資料不足|指標無有效數值"):
                agent.evaluate_weekly_signal(self.data.tail(count))
        signal = self.evaluate_colors(
            "yellow", "maroon", "green", 10.0, data=self.data.tail(39)
        )
        self.assertTrue(signal.passed)

    def test_bad_ohlc_fails_closed(self):
        for value in (np.nan, np.inf, -np.inf, 0.0, -1.0):
            data = self.data.copy()
            data.iloc[20, data.columns.get_loc("Open")] = value
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "OHLC"):
                agent.evaluate_weekly_signal(data)

    def test_ohlc_range_is_not_validated_or_repaired(self):
        for column, value in (("High", 1.0), ("Low", 600.0),
                              ("Open", 600.0), ("Close", 600.0)):
            data = self.data.copy()
            data.at[data.index[-1], column] = value
            original = data.copy(deep=True)
            with self.subTest(column=column), \
                    patch.object(agent.indicators, "darvas_box_series",
                                 wraps=agent.indicators.darvas_box_series) as darvas:
                signal = agent.evaluate_weekly_signal(data)
                self.assertIn("Darvas", signal.summary)
                pd.testing.assert_frame_equal(darvas.call_args.args[0], original)
                pd.testing.assert_frame_equal(data, original)

    def test_missing_columns_and_bad_index_fail_closed(self):
        for data in (self.data.drop(columns="Low"), self.data.reset_index(drop=True),
                     self.data.iloc[:0], pd.concat([self.data, self.data.tail(1)])):
            with self.subTest(shape=data.shape), self.assertRaises(ValueError):
                agent.evaluate_weekly_signal(data)

    def test_all_series_use_same_weekly_data_including_current_wednesday(self):
        close = np.linspace(100.0, 500.0, 500)
        daily = pd.DataFrame(
            {"Open": close - 1, "High": close + 2, "Low": close - 2,
             "Close": close, "Volume": 1000.0},
            index=pd.bdate_range(end="2026-09-30", periods=500, tz="Asia/Taipei"),
        )
        daily.iloc[30, daily.columns.get_loc("High")] = 220.0
        expected = agent.indicators.to_weekly(daily)
        with patch.object(agent.indicators, "darvas_box_series",
                          wraps=agent.indicators.darvas_box_series) as darvas, \
                patch.object(agent.indicators, "squeeze_momentum_series",
                             wraps=agent.indicators.squeeze_momentum_series) as squeeze, \
                patch.object(agent.indicators, "kalman_trend_series",
                             wraps=agent.indicators.kalman_trend_series) as kalman, \
                patch.object(agent.indicators, "calculate_weekly_filters",
                             wraps=agent.indicators.calculate_weekly_filters) as filters:
            signal = agent.evaluate_weekly_signal(daily)
        for calculation in (darvas, squeeze, kalman, filters):
            pd.testing.assert_frame_equal(calculation.call_args.args[0], expected)
        self.assertEqual(expected["Close"].iloc[-1], daily["Close"].iloc[-1])
        self.assertEqual(expected.index[-1].date().isoformat(), "2026-10-02")
        self.assertIn("2026-10-02", signal.summary)


class HistoryValidationTests(unittest.TestCase):
    def setUp(self):
        self.data = weekly_history()
        self.stock = agent.Stock("2330.TW", "TW", "Test")
        self.now = datetime(2026, 10, 2, 4, tzinfo=timezone.utc)
        self.quote = agent.Quote(float(self.data["Close"].iloc[-1]),
                                 self.data.index[-1].to_pydatetime())

    def test_matching_history_passes(self):
        confirmed_at = datetime(2026, 10, 2, 14, 0, tzinfo=agent.TPE)
        current_quote = agent.Quote(500.0, confirmed_at)
        after_close = datetime(2026, 10, 2, 6, 0, tzinfo=timezone.utc)
        with patch.object(agent, "fetch_price_history", return_value=self.data) as fetch:
            self.assertTrue(
                agent.fetch_weekly_signal(self.stock, current_quote, after_close).passed
            )
        fetch.assert_called_once_with(self.stock, "5y")

    def test_current_quote_is_used_for_kalman_price_gap(self):
        quote = agent.Quote(125.0, self.quote.as_of)
        expected = agent.WeeklySignal(True, "summary", "reason")
        with patch.object(agent, "fetch_price_history", return_value=self.data), \
                patch.object(agent, "evaluate_weekly_signal", return_value=expected) as evaluate:
            result = agent.fetch_weekly_signal(self.stock, quote, self.now)
        self.assertIs(result, expected)
        evaluate.assert_called_once()
        self.assertEqual(evaluate.call_args.kwargs["current_price"], quote.price)

    def test_weekly_kalman_excludes_unconfirmed_current_week(self):
        dates = pd.bdate_range(end="2026-10-05", periods=500, tz="America/New_York")
        close = np.linspace(20.0, 100.0, len(dates))
        daily = pd.DataFrame(
            {"Open": close - 1, "High": close + 2, "Low": close - 2,
             "Close": close, "Volume": 1000.0},
            index=dates,
        )
        quote_time = datetime(2026, 10, 5, 12, 0, tzinfo=agent.MARKETS["US"][0])
        quote = agent.Quote(float(close[-1] + 0.5), quote_time)
        now = quote_time.astimezone(timezone.utc)
        weekly = agent.indicators.to_weekly(daily)
        expected_kalman_data = weekly.iloc[:-1].copy()
        original = daily.copy(deep=True)

        darvas = pd.DataFrame(
            {"top": 101.0, "bottom": 99.0, "color": "green"}, index=weekly.index
        )
        squeeze = pd.DataFrame(
            {"val": 1.0, "color": "lime"}, index=weekly.index
        )
        with patch.object(agent, "fetch_price_history", return_value=daily), \
                patch.object(agent.indicators, "darvas_box_series", return_value=darvas), \
                patch.object(agent.indicators, "squeeze_momentum_series",
                             return_value=squeeze), \
                patch.object(agent.indicators, "kalman_trend_series",
                             wraps=agent.indicators.kalman_trend_series) as kalman:
            signal = agent.fetch_weekly_signal(
                agent.Stock("ATEX", "US", "Anterix Inc."), quote, now
            )

        pd.testing.assert_frame_equal(kalman.call_args.args[0], expected_kalman_data)
        self.assertEqual(expected_kalman_data.index[-1].date().isoformat(), "2026-10-02")
        self.assertTrue(agent.indicators.is_weekly(expected_kalman_data))
        self.assertIn("已確認周 K", signal.summary)
        self.assertNotIn("已完成周 K", signal.summary)
        pd.testing.assert_frame_equal(daily, original)

    def test_kalman_input_excludes_current_week_daily_bars(self):
        dates = pd.bdate_range(end="2026-10-06", periods=10, tz="America/New_York")
        close = np.arange(100.0, 110.0)
        daily = pd.DataFrame(
            {"Open": close - 1, "High": close + 1, "Low": close - 2,
             "Close": close, "Volume": 1000.0},
            index=dates,
        )
        as_of = datetime(2026, 10, 6, 12, 0, tzinfo=agent.MARKETS["US"][0])
        result = agent.build_kalman_input(daily, as_of, "US")

        expected = agent.indicators.to_weekly(daily.loc[
            pd.Index(daily.index.date) < as_of.date() - timedelta(days=as_of.weekday())
        ])
        pd.testing.assert_frame_equal(result, expected)
        self.assertEqual(result.index[-1].date().isoformat(), "2026-10-02")
        self.assertTrue(agent.indicators.is_weekly(result))

    def test_kalman_input_does_not_add_quote_bar_when_today_missing(self):
        dates = pd.bdate_range(end="2026-10-05", periods=10, tz="America/New_York")
        daily = pd.DataFrame(
            {"Open": 100.0, "High": 101.0, "Low": 99.0, "Close": 100.0,
             "Volume": 1000.0},
            index=dates,
        )
        as_of = datetime(2026, 10, 6, 12, 0, tzinfo=agent.MARKETS["US"][0])
        result = agent.build_kalman_input(daily, as_of, "US")

        self.assertEqual(result.index[-1].date().isoformat(), "2026-10-02")
        self.assertEqual(float(result["Close"].iloc[-1]), 100.0)

    def test_confirmed_history_does_not_require_current_week_data(self):
        as_of = datetime(2026, 10, 6, 12, 0, tzinfo=agent.MARKETS["US"][0])
        pd.testing.assert_frame_equal(
            agent.build_kalman_input(self.data, as_of, "US"), self.data
        )
        quote = agent.Quote(500.0, as_of)
        with patch.object(agent, "fetch_price_history", return_value=self.data):
            signal = agent.fetch_weekly_signal(
                agent.Stock("AMD", "US", "AMD"), quote, as_of
            )
        self.assertTrue(signal.passed)
        self.assertIn("已確認周 K", signal.summary)

    def test_friday_bar_is_confirmed_only_after_local_market_close(self):
        for market, zone, hour, minute in (
                ("US", agent.MARKETS["US"][0], 16, 0),
                ("TW", agent.TPE, 13, 30)):
            data = self.data.copy()
            data.index = data.index.tz_convert(zone)
            # Use local Friday midnight labels for both markets.
            data.index = pd.date_range(
                end="2026-10-02", periods=len(data), freq="W-FRI", tz=zone
            )
            close = datetime(2026, 10, 2, hour, minute, tzinfo=zone)
            with self.subTest(market=market):
                pd.testing.assert_frame_equal(
                    agent.build_kalman_input(data, close - timedelta(minutes=1), market),
                    data.iloc[:-1],
                )
                pd.testing.assert_frame_equal(
                    agent.build_kalman_input(data, close, market), data
                )
                pd.testing.assert_frame_equal(
                    agent.build_kalman_input(data.iloc[:-1], close, market),
                    data.iloc[:-1],
                )

    def test_missing_stale_future_inconsistent_and_corrupt_history(self):
        missing = self.data.copy()
        missing.iloc[20, missing.columns.get_loc("Low")] = np.nan
        future = self.data.copy()
        future.index = future.index + pd.Timedelta(days=7)
        cases = (None, self.data.iloc[:-2], future,
                 missing, self.data.drop(columns="Open"))
        for data in cases:
            with self.subTest(data_type=type(data).__name__), \
                    patch.object(agent, "fetch_price_history", return_value=data):
                signal = agent.fetch_weekly_signal(self.stock, self.quote, self.now)
                self.assertFalse(signal.passed)
                self.assertIn("無數據", signal.reason)

    def test_infinite_quote_is_rejected(self):
        quote_time = self.now.astimezone(agent.TPE) - pd.Timedelta(minutes=1)
        data = pd.DataFrame(
            {"Close": [np.inf]},
            index=pd.DatetimeIndex([quote_time]),
        )
        with patch.object(agent, "fetch_price_history", return_value=data) as fetch:
            self.assertIsNone(agent.fetch_quote(self.stock, self.now))
        fetch.assert_called_once_with(self.stock, "1d", interval="1m", prepost=True)

    def test_minute_quote_must_be_for_today_and_not_future(self):
        quote_time = self.now.astimezone(agent.TPE) - pd.Timedelta(minutes=1)
        fresh = pd.DataFrame({"Close": [100.0]}, index=pd.DatetimeIndex([quote_time]))
        with patch.object(agent, "fetch_price_history", return_value=fresh):
            quote = agent.fetch_quote(self.stock, self.now)
        self.assertIsNotNone(quote)
        self.assertEqual(quote.price, 100.0)

        delayed = fresh.copy()
        delayed.index = pd.DatetimeIndex([self.now.astimezone(agent.TPE) - pd.Timedelta(minutes=20)])
        with patch.object(agent, "fetch_price_history", return_value=delayed):
            quote = agent.fetch_quote(self.stock, self.now)
        self.assertIsNotNone(quote)

        for offset in (pd.Timedelta(minutes=5), pd.Timedelta(days=-1)):
            invalid = fresh.copy()
            invalid.index = pd.DatetimeIndex([self.now.astimezone(agent.TPE) + offset])
            with self.subTest(offset=offset), \
                    patch.object(agent, "fetch_price_history", return_value=invalid):
                self.assertIsNone(agent.fetch_quote(self.stock, self.now))

    def test_market_monitoring_windows(self):
        cases = (
            (datetime(2026, 10, 2, 0, 0, tzinfo=timezone.utc), "TW", True),
            (datetime(2026, 10, 2, 1, 0, tzinfo=timezone.utc), "TW", True),
            (datetime(2026, 10, 2, 5, 30, tzinfo=timezone.utc), "TW", True),
            (datetime(2026, 10, 2, 5, 40, tzinfo=timezone.utc), "TW", False),
            (datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc), "US", True),
            (datetime(2026, 10, 2, 13, 30, tzinfo=timezone.utc), "US", True),
            (datetime(2026, 10, 3, 0, 0, tzinfo=timezone.utc), "US", False),
            (datetime(2026, 11, 2, 9, 0, tzinfo=timezone.utc), "US", True),
            (datetime(2026, 10, 3, 0, 0, tzinfo=timezone.utc), "TW", False),
        )
        for now, market, expected in cases:
            with self.subTest(now=now, market=market):
                self.assertEqual(agent.is_monitoring_window(market, now), expected)


class NotificationGateTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 2, 4, tzinfo=timezone.utc)
        self.stock = agent.Stock("2330.TW", "TW", "Test")
        self.args = argparse.Namespace(force=False, all_markets=False, dry_run=True, market=None)
        self.real_fetch_quote = agent.fetch_quote
        self.real_fetch_signal = agent.fetch_weekly_signal
        self.real_should_run = agent.should_run
        self.real_mark_run = agent.mark_run
        self.patches = (
            patch.object(agent, "load_rules", return_value=agent.Rules()),
            patch.object(agent, "should_run", return_value=True),
            patch.object(agent, "_utc_now", return_value=self.now),
            patch.object(agent, "load_watchlist", return_value=[self.stock]),
            patch.object(agent, "mark_run"),
            patch.object(agent, "append_history"),
            patch.object(agent, "fetch_quote"),
            patch.object(agent, "fetch_weekly_signal"),
            patch.object(
                agent.notifier, "notify_batch",
                return_value={self.stock.symbol.upper(): agent.notifier.DRY_RUN},
            ),
            patch.object(agent.tv_screener, "update_watchlist", return_value=[]),
            patch.object(agent.tv_sell_monitor, "check_watchlist", return_value=[]),
            patch.object(agent, "load_watchlist_failures", return_value={}),
            patch.object(agent, "save_watchlist_failures", return_value=True),
        )
        self.mocks = [p.start() for p in self.patches]
        for p in self.patches:
            self.addCleanup(p.stop)
        self.rules, self.should_run, self.utc_now, _, self.mark, self.history, self.quote, \
            self.signal, self.notify_batch, self.refresh, self.sell_monitor, \
            self.failure_counts, self.save_failures = self.mocks
        self.signal.return_value = agent.WeeklySignal(
            True, "Darvas yellow | Squeeze maroon | Kalman green | 周線過濾 通過",
            "三個周線指標與周線技能過濾同時通過"
        )

    def test_failed_or_missing_signal_blocks_bot(self):
        self.quote.return_value = agent.Quote(106.0, self.now)
        for reason in ("未通過：Darvas 非紅色", "未通過：Squeeze 非紅色",
                       "未通過：Kalman 趨勢強度 >= -10", "未通過：周線技能過濾",
                       "無數據：周線資料不足"):
            with self.subTest(reason=reason):
                self.signal.return_value = agent.WeeklySignal(False, "Test states", reason)
                agent.run_once(self.args, self.now)
                self.notify_batch.assert_not_called()
                self.assertIn(reason, self.history.call_args.args[1][-1])
                self.assertNotIn("漲跌幅", self.history.call_args.args[1][-1])



    def test_missing_quote_blocks_signal_and_bot(self):
        self.quote.return_value = None
        agent.run_once(self.args, self.now)
        self.signal.assert_not_called()
        self.notify_batch.assert_not_called()
        self.assertIn("無數據", self.history.call_args.args[1][-1])

    def test_aggregates_passed_stocks_after_filtering_the_entire_watchlist(self):
        second = agent.Stock("2317.TW", "TW", "鴻海")
        events = []

        def fetch_quote(stock, _now):
            events.append(f"quote:{stock.symbol}")
            return agent.Quote(106.0, self.now)

        def fetch_signal(stock, _quote, _now):
            events.append(f"signal:{stock.symbol}")
            return agent.WeeklySignal(
                True, "有效指標", "三個周線指標與周線技能過濾同時通過"
            )

        def notify_batch(alerts, title, **_kwargs):
            events.append("notify")
            self.assertEqual(title, "本輪訊號通過｜市場 TW")
            self.assertEqual(
                [symbol for symbol, _ in alerts],
                [self.stock.symbol, second.symbol],
            )
            return {
                self.stock.symbol.upper(): agent.notifier.DRY_RUN,
                second.symbol.upper(): agent.notifier.DRY_RUN,
            }

        self.quote.side_effect = fetch_quote
        self.signal.side_effect = fetch_signal
        self.notify_batch.side_effect = notify_batch
        with patch.object(agent, "load_watchlist", return_value=[self.stock, second]):
            agent.run_once(self.args, self.now)

        self.assertEqual(events, [
            "quote:2330.TW", "signal:2330.TW",
            "quote:2317.TW", "signal:2317.TW", "notify",
        ])
        self.notify_batch.assert_called_once()

    def test_run_once_checks_sell_volume_watchlist_and_records_result(self):
        self.quote.return_value = None
        self.sell_monitor.return_value = ["**NASDAQ:INTC**｜週線成交量柱 綠色"]

        agent.run_once(self.args, self.now)

        self.sell_monitor.assert_called_once_with(
            self.now, cooldown_minutes=agent.Rules().cooldown_minutes, dry_run=True
        )
        self.assertIn(
            "**NASDAQ:INTC**｜週線成交量柱 綠色",
            self.history.call_args.args[1],
        )

    def test_sent_telegram_notification_adds_symbol_to_market_watchlist(self):
        self.args.dry_run = False
        self.quote.return_value = agent.Quote(106.0, self.now)
        self.notify_batch.return_value = {self.stock.symbol.upper(): agent.notifier.SENT}
        client = unittest.mock.Mock()

        with patch.object(agent.tv_mcp, "TVMCPClient", return_value=client) as create_client:
            agent.run_once(self.args, self.now)

        create_client.assert_called_once_with()
        client.add_symbol_to_watchlist.assert_called_once_with(
            "台股Screener", self.stock.symbol, self.stock.market
        )
        self.assertIn("TradingView「台股Screener」已加入", self.history.call_args.args[1][-1])

    def test_non_sent_telegram_notification_does_not_connect_to_tradingview(self):
        self.quote.return_value = agent.Quote(106.0, self.now)
        with patch.object(agent.tv_mcp, "TVMCPClient") as create_client:
            agent.run_once(self.args, self.now)
        create_client.assert_not_called()

    def test_tradingview_sync_failure_is_recorded_after_sent_notification(self):
        self.args.dry_run = False
        self.quote.return_value = agent.Quote(106.0, self.now)
        self.notify_batch.return_value = {self.stock.symbol.upper(): agent.notifier.SENT}
        client = unittest.mock.Mock()
        client.add_symbol_to_watchlist.side_effect = agent.tv_mcp.TVMCPError("MCP unavailable")

        with patch.object(agent.tv_mcp, "TVMCPClient", return_value=client):
            self.assertEqual(agent.run_once(self.args, self.now), 0)

        self.assertIn(
            "TradingView「台股Screener」同步失敗：MCP unavailable",
            self.history.call_args.args[1][-1],
        )
        self.assertIn("通知結果 sent", self.history.call_args.args[1][-1])

    def test_removes_after_three_consecutive_valid_signal_failures(self):
        self.quote.return_value = agent.Quote(106.0, self.now)
        self.signal.return_value = agent.WeeklySignal(
            False, "有效指標但條件不符", "未通過：Darvas 非紅色"
        )
        client = unittest.mock.Mock()
        client.remove_symbol_from_watchlist.return_value = True
        saved_counts = []
        self.save_failures.side_effect = lambda counts: saved_counts.append(dict(counts)) or True

        with patch.object(agent.tv_mcp, "TVMCPClient", return_value=client) as create_client:
            for _ in range(agent.WATCHLIST_FAILURE_LIMIT):
                agent.run_once(self.args, self.now)

        self.assertEqual(
            [snapshot[self.stock.symbol] for snapshot in saved_counts[:3]],
            [1, 2, 3],
        )
        client.remove_symbol_from_watchlist.assert_called_once_with(
            "台股Screener", self.stock.symbol, self.stock.market
        )
        self.assertNotIn(self.stock.symbol, self.failure_counts.return_value)
        self.assertEqual(saved_counts[-1], {})
        self.assertIn(
            "已移除（連續未通過 3 次）",
            self.history.call_args.args[1][-1],
        )
        create_client.assert_called_once_with()

    def test_no_data_does_not_increment_or_remove(self):
        self.quote.return_value = agent.Quote(106.0, self.now)
        self.signal.return_value = agent.WeeklySignal(
            False, "無數據", "無數據：指標歷史資料不足"
        )
        self.failure_counts.return_value[self.stock.symbol] = 2
        with patch.object(agent.tv_mcp, "TVMCPClient") as create_client:
            agent.run_once(self.args, self.now)
        self.assertEqual(self.failure_counts.return_value[self.stock.symbol], 2)
        self.save_failures.assert_not_called()
        create_client.assert_not_called()

    def test_passing_signal_resets_failures_even_during_cooldown(self):
        self.quote.return_value = agent.Quote(106.0, self.now)
        self.failure_counts.return_value[self.stock.symbol] = 2
        self.notify_batch.return_value = {self.stock.symbol.upper(): agent.notifier.COOLDOWN}

        with patch.object(agent.tv_mcp, "TVMCPClient") as create_client:
            agent.run_once(self.args, self.now)

        self.assertNotIn(self.stock.symbol, self.failure_counts.return_value)
        self.save_failures.assert_called_once_with({})
        create_client.assert_not_called()

    def test_does_not_remove_when_failure_count_cannot_be_saved(self):
        self.quote.return_value = agent.Quote(106.0, self.now)
        self.signal.return_value = agent.WeeklySignal(
            False, "有效指標但條件不符", "未通過：Darvas 非紅色"
        )
        self.failure_counts.return_value[self.stock.symbol] = (
            agent.WATCHLIST_FAILURE_LIMIT - 1
        )
        self.save_failures.return_value = False
        with patch.object(agent.tv_mcp, "TVMCPClient") as create_client:
            agent.run_once(self.args, self.now)
        create_client.assert_not_called()
        self.assertIn(
            "未能保存連續未通過次數，為避免誤刪已略過",
            self.history.call_args.args[1][-1],
        )


    def test_refresh_failure_stops_quotes_and_notifications(self):
        self.refresh.side_effect = agent.tv_screener.TVNoData("來源失敗")
        self.assertEqual(agent.run_once(self.args, self.now), 1)
        self.quote.assert_not_called()
        self.signal.assert_not_called()
        self.notify_batch.assert_not_called()
        self.assertIn("清單更新失敗", self.history.call_args.args[1][0])

    def test_refresh_precedes_loading_new_watchlist_and_fetching_quotes(self):
        self.args.market = "TW"
        events = []
        new_stock = agent.Stock("2454.TW", "TW", "New")
        self.refresh.side_effect = lambda **kwargs: events.append("refresh") or []
        self.quote.side_effect = lambda stock, now: events.append(stock.symbol)
        with patch.object(agent, "load_watchlist",
                          side_effect=lambda: events.append("load") or [new_stock]):
            agent.run_once(self.args, self.now)
        self.assertEqual(events, ["refresh", "load", "2454.TW"])
        self.assertTrue(self.refresh.call_args.kwargs["require_all"])
        self.assertEqual(
            {source.market for source in self.refresh.call_args.kwargs["sources"]}, {"TW"}
        )

    def test_opening_cooloff_still_blocks_all_fetches_even_with_override(self):
        self.args.force = True
        self.args.all_markets = True
        opening = datetime(2026, 10, 2, 1, 10, tzinfo=timezone.utc)
        agent.run_once(self.args, opening)
        self.quote.assert_not_called()
        self.signal.assert_not_called()
        self.notify_batch.assert_not_called()
        self.refresh.assert_called_once()

    def test_closed_market_blocks_fetches(self):
        self.args.market = "TW"
        closed = datetime(2026, 10, 2, 8, tzinfo=timezone.utc)
        agent.run_once(self.args, closed)
        self.quote.assert_not_called()
        self.signal.assert_not_called()
        self.notify_batch.assert_not_called()
        self.refresh.assert_not_called()

    def test_explicit_market_filters_mixed_watchlist_even_with_time_override(self):
        us_stock = agent.Stock("AAPL", "US", "Apple")
        self.args.all_markets = True
        self.quote.return_value = agent.Quote(100.0, self.now)
        with patch.object(agent, "load_watchlist", return_value=[self.stock, us_stock]):
            for market, expected in (("TW", self.stock), ("US", us_stock)):
                with self.subTest(market=market):
                    self.args.market = market
                    self.quote.reset_mock()
                    self.notify_batch.reset_mock()
                    self.notify_batch.return_value = {
                        expected.symbol.upper(): agent.notifier.DRY_RUN
                    }
                    agent.run_once(self.args, self.now)
                    self.quote.assert_called_once_with(expected, self.now)
                    self.notify_batch.assert_called_once()
                    self.assertEqual(
                        self.notify_batch.call_args.args[0][0][0], expected.symbol
                    )
                    self.mark.assert_called_with(self.now, market)
                    self.assertEqual(
                        {s.market for s in self.refresh.call_args.kwargs["sources"]}, {market}
                    )

    def test_us_task_does_not_fetch_tw_at_overlapping_0800_slot(self):
        self.args.market = "US"
        overlap = datetime(2026, 11, 3, 0, 0, tzinfo=timezone.utc)
        us_stock = agent.Stock("AAPL", "US", "Apple")
        self.quote.return_value = None
        with patch.object(agent, "load_watchlist", return_value=[self.stock, us_stock]):
            agent.run_once(self.args, overlap)
        self.quote.assert_called_once_with(us_stock, self.now)

    def test_waiting_for_lock_preserves_taiwan_0800_slot(self):
        self.args.market = "TW"
        slot = datetime(2026, 11, 3, 0, 0, tzinfo=timezone.utc)
        later = datetime(2026, 11, 3, 0, 3, tzinfo=timezone.utc)
        self.quote.return_value = None
        agent.run_once(self.args, later, scheduled_at=slot)
        self.quote.assert_called_once_with(self.stock, self.now)

    def test_quote_validation_uses_fresh_time_after_slow_run_setup(self):
        run_started = self.now - timedelta(minutes=2)
        self.args.all_markets = True
        self.quote.return_value = None
        with patch.object(agent.notifier, "is_market_opening_cooloff", return_value=False):
            agent.run_once(self.args, run_started)

        self.assertEqual(self.quote.call_args.args[0], self.stock)
        self.assertEqual(self.quote.call_args.args[1], self.now)
        self.assertGreater(
            self.quote.call_args.args[1] - run_started, timedelta(minutes=1)
        )

    def test_market_throttle_files_are_independent(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(agent, "CACHE", Path(directory)):
            self.real_mark_run(self.now, "TW")
            self.assertFalse(self.real_should_run(self.now, 10, "TW"))
            self.assertTrue(self.real_should_run(self.now, 10, "US"))

    def test_run_interval_still_blocks_fetches(self):
        self.should_run.return_value = False
        agent.run_once(self.args, self.now)
        self.quote.assert_not_called()
        self.signal.assert_not_called()
        self.notify_batch.assert_not_called()
        self.mark.assert_not_called()

    def test_run_once_with_real_series_and_mocked_data_and_bot(self):
        data = weekly_history()
        data.iloc[-1, data.columns.get_loc("Close")] = data["Close"].iloc[-2] * 1.06
        data.iloc[-1, data.columns.get_loc("High")] = data["Close"].iloc[-1] + 2
        self.quote.side_effect = self.real_fetch_quote
        self.signal.side_effect = self.real_fetch_signal
        quote_time = self.now.astimezone(agent.TPE) - pd.Timedelta(minutes=1)
        for current_price, passed in ((500.0, True), (600.0, False)):
            with self.subTest(current_price=current_price):
                self.notify_batch.reset_mock()
                self.mark.reset_mock()
                intraday = pd.DataFrame(
                    {"Close": [current_price]},
                    index=pd.DatetimeIndex([quote_time]),
                )
                with patch.object(agent, "fetch_price_history",
                                  side_effect=[intraday, data]) as fetch:
                    agent.run_once(self.args, self.now)
                self.assertEqual([c.args[1] for c in fetch.call_args_list], ["1d", "5y"])
                self.assertEqual(fetch.call_args_list[0].kwargs,
                                 {"interval": "1m", "prepost": True})
                if passed:
                    self.notify_batch.assert_called_once()
                    self.assertIn("三個周線指標與周線技能過濾同時通過",
                                  self.history.call_args.args[1][-1])
                    self.assertEqual(
                        self.notify_batch.call_args.args[0][0][1],
                        f"{self.stock.symbol} {self.stock.name}\n現價 {current_price:.2f}",
                    )
                    self.assertNotIn("🔻", self.notify_batch.call_args.args[0][0][1])
                else:
                    self.notify_batch.assert_not_called()
                    self.assertIn("未通過：現價與 Kalman line 價差 < 7%",
                                  self.history.call_args.args[1][-1])
                self.assertNotIn("漲跌幅", self.history.call_args.args[1][-1])
                self.mark.assert_called_once_with(self.now, None)


class RulesPathTests(unittest.TestCase):
    def test_default_rules_are_loaded_from_project_root(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "rules.md"
            path.write_text("- cooldown_minutes: 45\n"
                            "- run_interval_minutes: 20\n"
                            "- market_hours_only: false\n", encoding="utf-8")
            rules = agent.load_rules(path)
            self.assertEqual(agent.load_rules.__defaults__, (agent.ROOT / "rules.md",))
            self.assertEqual(rules.cooldown_minutes, 45)
            self.assertEqual(rules.run_interval_minutes, 20)
            self.assertFalse(rules.market_hours_only)
        self.assertTrue((agent.ROOT / "rules.md").is_file())
        self.assertFalse((agent.DATA / "rules.md").exists())
        self.assertEqual(agent.load_rules(), agent.load_rules(agent.ROOT / "rules.md"))


class WatchlistRefreshTests(unittest.TestCase):
    def test_partial_failure_keeps_file_unchanged_in_strict_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "watchlist.md"
            original = "# Watchlist\n\n| symbol | market | name | note |\n"
            path.write_text(original, encoding="utf-8")
            with patch.object(agent.tv_screener, "fetch_all",
                              return_value=({"tw_screener": []}, {"tw_best": "offline"})):
                with self.assertRaises(agent.tv_screener.TVNoData):
                    agent.tv_screener.update_watchlist(path=path, require_all=True)
            self.assertEqual(path.read_text(encoding="utf-8"), original)

    def test_refresh_preserves_source_description_manual_and_other_market_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "watchlist.md"
            header = "# Watchlist\n\n## TradingView sources\nCustom description\n\n"
            path.write_text(
                header + "| symbol | market | name | note |\n"
                "|--------|--------|------|------|\n"
                "| 2330.TW | TW | Manual | |\n"
                "| 2317.TW | TW | Old | tv:tw_screener |\n"
                "| AAPL | US | Apple | tv:us_screener |\n",
                encoding="utf-8",
            )
            row = agent.tv_screener.Row("2454.TW", "TW", "New",
                                       sources=["tw_screener"])
            with patch.object(agent.tv_screener, "fetch_all",
                              return_value=({"tw_screener": [row]}, {})):
                agent.tv_screener.update_watchlist(path=path, require_all=True)
            content = path.read_text(encoding="utf-8")
            self.assertTrue(content.startswith(header))
            for symbol in ("2330.TW", "2454.TW", "AAPL"):
                self.assertIn(symbol, content)
            self.assertNotIn("2317.TW", content)


if __name__ == "__main__":
    unittest.main()
