# TradingView Screener 模組說明

本文件依照 [`tv_screener.py`](tv_screener.py) 說明目前的來源設定、資料抓取、代碼轉換，以及 `data/watchlist.md` 的合併與更新方式。模組負責取得 TradingView 清單並維護監控清單；報價、指標判斷與通知由其他模組處理。

## 預設來源

| 來源 key | 市場 | 類型 | 用途與預設條件 |
|----------|------|------|----------------|
| `tw_screener` | 台股 | `scan` | 市值至少 50 億 TWD、收盤價不低於日線 SMA200、月成交金額大於 100 億 TWD、1 年 Beta 大於 1；最多取 500 筆，依市值遞減。 |
| `tw_best` | 台股 | `html` | TradingView 台股 Best Performing 頁面。HTML 無法取得時會嘗試 scanner payload。 |
| `us_screener` | 美股 | `scan` | 市值至少 20 億 USD、收盤價不低於日線 SMA200、月成交金額大於 9 億 USD、1 年 Beta 大於 1；最多取 500 筆，依市值遞減。 |
| `us_best` | 美股 | `html` | TradingView 美股 Best Performing 頁面。HTML 無法取得時會嘗試 scanner payload。 |

條件掃描的預設 scanner payload 內建於程式。自訂 scanner 可使用 `data/tv_scans/<來源key>.json` 提供 payload；來源本身有 `params` 時，會優先使用來源設定的 payload。

## 來源設定

若存在 `data/tv_sources.json`，`load_sources()` 會從該 JSON 載入來源；檔案不存在、內容格式錯誤或來源清單為空時，會記錄警告並改用內建預設來源。自訂來源可包含：

- `key`：來源識別名稱，亦用於自訂 scanner payload 檔名及 watchlist 的來源註記。
- `market`：`TW` 或 `US`。
- `kind`：抓取方式，支援 `html`、`scan`、`mcp_watchlist`、`mcp_screener`。
- `url`：HTML 頁面網址。
- `params`：來源專用參數；`scan` 可放 TradingView scanner payload，`mcp_watchlist` 需提供數字 `watchlist_id`，`mcp_screener` 的參數會傳入 MCP 的 `run_screener`。

`mcp_*` 來源需要先透過 `python -m skills.tv_auth login` 完成 TradingView OAuth 授權。TradingView MCP 的 watchlist ID 必須是數字；私人 screener 分享網址中的 ID 不可直接當作 watchlist ID 使用。

## 抓取流程與代碼轉換

來源抓取會依 `kind` 選擇 HTML、scanner 或 MCP：

- `html`：以帶有瀏覽器 User-Agent 的 HTTP session 讀取頁面，解析 `<tr data-rowkey="交易所:代碼">` 及名稱。HTTP 非 200、頁面沒有可解析的列或其他抓取錯誤會視為該來源失敗，接著嘗試 scanner payload。
- `scan`：向 `scanner.tradingview.com/<市場>/scan` POST JSON payload，確保回傳欄位包含 `description` 以取得名稱；HTTP 錯誤或空結果會視為失敗。
- `mcp_watchlist`：透過 MCP 讀取指定 watchlist，並略過以 `###` 開頭的分隔標題。
- `mcp_screener`：透過 MCP 執行指定市場的 screener，使用回傳列的 symbol 與 description/name。

TradingView 代碼會依交易所轉換成 yfinance 代碼。台股 `TWSE` 會加上 `.TW`、`TPEX` 會加上 `.TWO`；美股只接受程式列出的交易所代碼（如 NASDAQ、NYSE、AMEX 等），並將代碼中的 `.` 或 `/` 轉成 `-`，例如 `BRK.B` 轉為 `BRK-B`。無法辨認或不屬於來源市場的代碼會略過。每個來源內重複的轉換後代碼只保留一次。

抓取失敗或無法取得有效代碼時，該來源會記錄失敗原因。MCP 授權不可用時，MCP 來源也會標記失敗，不會假裝取得空清單。

## Watchlist 合併與寫入

`update_watchlist()` 會讀取現有 watchlist，合併成功抓取的列，再視設定寫入或只預覽：

- 手動列（`note` 不以 `tv:` 開頭）保留，且排在自動列之前。
- 自動列以 `tv:<來源key>` 註記。相同代碼由多個來源取得時合併來源 key，並去除重複來源。
- 本次成功抓取的來源，其舊自動列由新結果取代；失敗來源的舊自動列會保留，避免短暫抓取失敗清空清單。
- 寫入時只替換 watchlist 表格，原有表格前言及說明保留；以暫存檔寫入後再原子替換目標檔。
- `dry_run=True` 只輸出合併後內容，不更動檔案。
- 所有來源皆失敗時回傳 `None`，不改寫檔案。`require_all=True` 時只要有任一來源失敗，就會引發 `TVNoData`，不套用部分成功結果。

排程由 `run_agent.py` 呼叫時採嚴格模式，指定市場的來源只要任一失敗，本輪即停止，不使用部分更新或舊清單繼續取價與通知。命令列手動更新預設為非嚴格模式：有來源成功就更新成功來源，並保留失敗來源先前的自動列。

## 常用命令

在專案根目錄使用專案虛擬環境：

```powershell
.\.venv\Scripts\python.exe -m skills.tv_screener --list-sources
.\.venv\Scripts\python.exe -m skills.tv_screener --dry-run --sources tw_screener,tw_best
.\.venv\Scripts\python.exe -m skills.tv_screener --sources us_screener,us_best
```

- `--list-sources`：列出目前來源 key、市場、類型與網址或參數。
- `--sources`：只執行逗號分隔的來源 key；未知 key 會以非零狀態結束。
- `--dry-run`：顯示合併結果但不寫入 watchlist。
- 不指定來源時，使用 `data/tv_sources.json` 或內建預設。

## 與監控主流程的關係

排程主流程先依市場篩選來源並呼叫 `update_watchlist(..., require_all=True)`，再載入最新 watchlist 進行報價及指標判斷。清單更新狀態與失敗原因記入每日歷史紀錄；本模組本身不抓取 Yahoo Finance 報價、不計算指標、不推播 Telegram。
