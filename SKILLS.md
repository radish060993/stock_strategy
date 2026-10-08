# SKILLS.md — 工具技能索引

本檔是可重用工具技能的目錄與調用入口，不是自動執行器。主流程由 [run_agent.py](run_agent.py) 匯入並呼叫 Python 模組，不會解析本文件執行命令。

## Hermes 文件分工

- [AGENTS.md](AGENTS.md)：Agent 角色、工作範圍與行為邊界。
- [rules.md](rules.md)：唯一的操作及通知規則來源，包括訊號門檻、資料有效性、冷卻與排程。
- [data/INDEX.md](data/INDEX.md)：跨 Session 記憶檔案與狀態索引。
- 本文件：技能目錄及各技能的調用入口；具體規則不在此重複維護。

## 技能目錄

| 技能 | 實作 | 用途與說明 |
|------|------|------------|
| indicators | [skills/indicators.py](skills/indicators.py) | Darvas Box、Squeeze Momentum、Adaptive Kalman Trend 與周線過濾；詳細行為見 [skills/indicators.md](skills/indicators.md)。 |
| tv_screener | [skills/tv_screener.py](skills/tv_screener.py) | TradingView 來源抓取及監控清單更新；來源設定、合併與命令見 [skills/tv_screener.md](skills/tv_screener.md)。 |
| notify | [skills/notify.py](skills/notify.py) | Telegram 單檔／批次推播、逐標的推播冷卻及市場開盤冷卻。 |
| tv_auth | [skills/tv_auth.py](skills/tv_auth.py) | TradingView OAuth 2.1 授權與 token 更新。 |
| tv_mcp | [skills/tv_mcp.py](skills/tv_mcp.py) | TradingView MCP watchlist、screener 與報價工具。 |
| tv_sell_monitor | [skills/tv_sell_monitor.py](skills/tv_sell_monitor.py) | 讀取「賣出提醒」watchlist 的週線 OHLCV，監控成交量柱由綠轉紅並透過 Telegram 通知。 |

## 常用調用入口

指標由 `run_agent.py` 的 `evaluate_weekly_signal` 統一計算並判斷；不要把單一指標的狀態當成最終通知判定。通知門檻以 [rules.md](rules.md) 為準。

```python
from skills import indicators

weekly = indicators.to_weekly(daily_ohlcv)
darvas = indicators.darvas_box_series(weekly)
squeeze = indicators.squeeze_momentum_series(weekly)
kalman = indicators.kalman_trend_series(weekly)
filters = indicators.calculate_weekly_filters(weekly)
```

排程主流程先依指定市場載入來源，再以嚴格模式更新 watchlist：

```python
from skills import tv_screener

sources = [source for source in tv_screener.load_sources()
           if source.market == market]
rows = tv_screener.update_watchlist(sources=sources, require_all=True)
```

`mcp_*` TradingView 來源的授權方式為 `python -m skills.tv_auth login`；screener 更新的手動命令見 [skills/tv_screener.md](skills/tv_screener.md)。
