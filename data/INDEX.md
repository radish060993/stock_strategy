# Memory Index

Agent 每次啟動時先讀這份檔案，再依需要載入其他記憶。

## 記憶檔案
- [watchlist.md](watchlist.md) — 監控標的清單（台股 + 美股）
- [rules.md](../rules.md) — 根目錄的通知與執行規則
- [SKILLS.md](../SKILLS.md) — 根目錄的工具技能索引與調用方式
- [history/](history/) — 每日執行紀錄，檔名 `YYYYMMDD.md`，檔案只追加；Stockbot 每次啟動時清除 14 天前的每日紀錄
- [cache/](cache/) — 暫存狀態，可安全刪除
- `cache/watchlist_failures.json` — 標的連續有效條件未通過次數；連續 3 次後才從相應 TradingView Screener 清單移除
- [tv_scans/](tv_scans/) — TradingView 自訂 screener 的 scanner payload（`<來源key>.json`，選用）
- `tv_sources.json` — 自訂抓取來源設定（選用，範例見 `tv_sources.example.json`）
- `cache/tv_oauth_token.json`、`cache/tv_oauth_client.json` — TradingView OAuth 憑證，**含敏感資訊，已列入 .gitignore，不可提交**

## TradingView 授權
```
python -m skills.tv_auth login     # OAuth 2.1 授權（PKCE，開瀏覽器）
python -m skills.tv_auth status    # 查看授權狀態
python -m skills.tv_mcp watchlists # 列出我的 watchlist 與 id
```
已知限制：TradingView MCP 未提供「以分享 ID 載入已存 screener」的工具，
`/screener/<id>/` 這類私人 screener 無法直接取得，請改用 `mcp_watchlist` 或 `mcp_screener` 來源。
  - `cooldown.json` — 各標的最後推播時間
  - `sell_volume_states.json` — TradingView「賣出提醒」清單週線量柱前次顏色
  - `last_run.json` — 未指定市場的手動執行時間（10 分鐘節流用）
  - `last_run_TW.json`、`last_run_US.json` — 台股／美股工作各自的上次執行時間，互不影響節流
  - `agent_run.lock` — 單一執行個體鎖

## Skills 登記表
技能登記與調用說明集中於 [SKILLS.md](../SKILLS.md)，新增技能時更新該檔，避免維護兩份登記表。

## 提煉紀錄（Lessons Learned）
<!-- Agent 從 history 中歸納出的經驗寫在這裡，例如：某標的常在開盤 5 分鐘內出現假突破 -->
