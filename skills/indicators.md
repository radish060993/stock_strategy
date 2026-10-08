# 技術指標模組說明

本文件依照 [`indicators.py`](indicators.py) 說明模組目前實際執行的資料處理、指標計算及回傳結果。模組提供 Darvas Box、Squeeze Momentum、Adaptive Kalman Trend，以及周線條件過濾；本身不抓取行情、不發送通知，也不決定最終通知資格。

## 輸入資料與共用處理

指標函式接收以 `DatetimeIndex` 為索引的 pandas `DataFrame`，OHLC 欄位必須存在；欄位名稱可為大小寫形式，會正規化為 `Open`、`High`、`Low`、`Close`、`Volume`，並依索引時間排序。`Volume` 只在相關運算需要成交量時才必須存在。

- `normalize_ohlcv(df)`：正規化欄名、確認 OHLC 欄位及時間索引，然後排序。缺少 OHLC 欄位或索引不是 `DatetimeIndex` 時會引發 `ValueError`。
- `is_weekly(df)`：以索引間隔的中位數是否至少 5 天，判斷資料是否已是周線；少於兩筆時回傳 `False`。
- `to_weekly(df, rule="W-FRI")`：已是周線時直接回傳；否則以週五為週期標籤，Open 取週內第一筆、High 取最高、Low 取最低、Close 取最後一筆、Volume 加總。最後一週可能尚未結束。

`*_series` 函式計算整段資料，適合繪圖或回測；`calculate_*` 函式通常取最新一根 K 棒並回傳狀態字典。各指標對資料不足的處理方式不同，詳見各節。

## Darvas Box

### 計算方式

`darvas_box_series(df, boxp=5)` 依 Darvas Box Pine 腳本的條件計算箱體上緣與下緣。`boxp` 至少為 3，否則會引發 `ValueError`。程式以近期高低點辨認箱體形成，並延續最近成立的箱體；收盤價高於上緣時標記為突破，低於下緣時標記為跌破。

### 回傳欄位

回傳的 `DataFrame` 與輸入資料使用相同索引，包含：

- `top`、`bottom`：箱體上緣與下緣。
- `color`：`green` 表示 Close 高於上緣；`red` 表示 Close 低於下緣；`yellow` 表示位於箱體範圍內。尚未形成箱體時為空值。
- `is_red`：`color` 是否為 `red`。

`calculate_darvas_box(df, boxp=5)` 回傳最新一根狀態，欄位為 `upper`、`lower`、`color`、`is_red`。尚未形成箱體時，狀態欄位為 `None`，並附上 `reason`。

## Squeeze Momentum

### 計算方式

`squeeze_momentum_series(df, length=20, mult=2.0, length_kc=20, mult_kc=1.5, use_true_range=True)` 計算 LazyBear Squeeze Momentum：

- Bollinger Bands 使用收盤價移動平均與標準差；標準差採母體標準差。預設參數為 BB(20, 2.0)。
- Keltner Channels 使用收盤價移動平均及平均價格區間；預設為 KC(20, 1.5)。`use_true_range=True` 時採 True Range，否則採 High-Low。
- `squeeze` 為 `on`（BB 位於 KC 內）、`off`（BB 位於 KC 外）或 `none`。
- `val` 是 `Close - mid` 的線性回歸值；直方圖顏色依 `val` 正負及相較前一筆的變化判定：`lime`（正值上升）、`green`（正值未上升）、`red`（非正值且下降）、`maroon`（非正值但未下降）。

此實作預設使用 BB 標準差倍數 2.0。若要讓 squeeze 開關點對應原 Pine 腳本中特定的 1.5 倍設定，可傳入 `mult=1.5`；`mult` 只影響 squeeze 開關，不影響直方圖的 `val` 與顏色。

### 回傳欄位

序列結果包含 `val`、`color`、`squeeze`、`upper_bb`、`lower_bb`、`upper_kc`、`lower_kc`。

`calculate_squeeze_momentum(df, **kwargs)` 回傳最新狀態：`val`、`color`、`is_red`、`passed`、`squeeze`。當顏色尚未形成時回傳空值狀態、`passed=False`，並附上資料不足原因。`passed=True` 表示顏色為 `lime`、`green` 或 `maroon`；`red` 表示直方圖非正且仍在下降。

## Adaptive Kalman Trend

### 計算方式

`kalman_trend_series(...)` 依輸入資料的時間框架逐根計算 Kalman 價格線與趨勢強度。預設參數為 `process_noise_1=0.01`、`process_noise_2=0.01`、`measurement_noise=500.0`、`trend_lookback=10`、`strength_smooth=10`、`osc_smooth=10`。

`model` 可選：

- `standard`：使用固定 measurement noise。
- `volume_adjusted`：依成交量調整 measurement noise；需要 `Volume` 欄位，缺少時會引發 `ValueError`。
- `parkinson_adjusted`：依當根與前一根的 High-Low 區間調整 measurement noise。

此程式依 Zeiierman Pine 腳本的數值運算計算：誤差共變矩陣每根 K 棒在預測前將兩個對角值重設為 1，非對角值延續前一根更新後的狀態；預測步驟的第二狀態為零。趨勢強度先以回看區間正規化，再經加權移動平均平滑；振盪值則是趨勢強度再經另一個加權移動平均。Stockbot 是否納入未收完當週的行為另見下節，不等同於 Pine 的確認時機。

### 回傳欄位

序列結果包含：

- `kalman`：Kalman 價格估計線。
- `trend_strength`：平滑後趨勢強度。
- `oscillator`：再平滑後的振盪值。
- `color`：趨勢強度絕對值未達 10 或尚無有效值時為 `blue`；達到門檻後，正值為 `green`、負值為 `red`。

`calculate_kalman_trend(df, weekly=True, include_current_bar=True, **kwargs)` 預設先轉成周線並納入當前尚未收完的周 K。`include_current_bar=False` 會排除最後一根資料。回傳最新 `trend_strength`、`oscillator`、`kalman`、`color`、`is_green` 與 `as_of`；趨勢強度不足時回傳空值狀態及 `reason`。其中 `is_green` 僅在顏色為 `green`（趨勢強度至少 10）時為真。

### Stockbot 的已確認周線計算與過濾條件

Stockbot 明確使用使用者 TradingView Inputs 的參數，不採用上述函式的原始預設值：

| TradingView Input | Stockbot 參數 | 設定值 |
|-------------------|---------------|--------|
| Measurement Noise | `measurement_noise` | 30 |
| Osc Smoothness | `osc_smooth` | 5 |
| Kalman Filter Model | `model` | `standard` |
| Trend Lookback | `trend_lookback` | 20 |
| Strength Smoothness | `strength_smooth` | 10 |

`process_noise_1` 與 `process_noise_2` 維持原腳本的 0.01。參數一致不代表行情來源與周 K 確認時機一致，不能據此保證與 TradingView 畫面數值完全相同。

Stockbot 只用最近已確認周 K 計算 Kalman line 與趨勢強度：盤中排除尚未收完的本週；週五市場收盤後且來源歷史包含當日才納入本週。最新有效分鐘報價只用於價格位置與價差判斷，不改寫 Kalman 輸入 Close。每日 K 先彙整成周 K，不把每日 K 或每次報價當成額外周 K，來源資料不會被改寫。`evaluate_weekly_signal` 的直接呼叫者須提供已確認周線；監控流程由 `build_kalman_input` 篩選。

依 [rules.md](../rules.md) 的現行規則，Kalman 部分必須同時符合以下三項：

| 檢查 | 通過條件 | 邊界判定 |
|------|----------|----------|
| 趨勢強度 | `trend_strength >= -10` | 剛好 -10 通過；低於 -10 不通過 |
| 價格位置 | 當前有效分鐘報價 `> Kalman line` | 等於或低於線不通過 |
| 百分比價差 | `(當前價 - Kalman line) / Kalman line * 100 < 7` | 剛好 7% 不通過；不取絕對值 |

價格位置與價差兩項合併，代表當前價必須高於 Kalman line，且高出的幅度小於 7%。強度條件直接比較 `trend_strength`，不是比較 `oscillator` 或要求顏色為綠色；剛好 -10 依指標配色仍為紅色，但符合強度門檻。`is_green` 的定義不變，亦不代表 Stockbot 的最終通知資格。

缺少已確認周線資料、必要指標數值無效或 Kalman line 非正數時，記錄「無數據」並略過通知，不建立虛構 K 棒。Kalman 三項通過後，仍須 Darvas、Squeeze、周線技能過濾及其他通知限制全部通過。此模式遵循 Pine 原腳本的 `barstate.isconfirmed` 計算時機，但不同行情來源、歷史範圍及調整方式仍可能造成數值差異。

## 周線技能過濾

`calculate_weekly_filters(df, doji_max_pct=8.0, doji_mode="open", volume_lookback=6, min_green_volume=3, volume_color_mode="open")` 會先確保資料為周線，然後逐項判斷下列條件：

| 檢查 | 預設通過條件 |
|------|--------------|
| `ma_trend` | 周收盤 SMA10 大於 SMA20 |
| `doji` | 當週實體幅度百分比不超過 8%；`open` 模式以 Open 為分母，`range` 模式以 High-Low 為分母 |
| `volume_green` | 前 6 週（不含本週）至少 3 週符合綠色量柱判定 |
| `not_consecutive_red_volume` | 本週和上週不可同時為紅色量柱；只有本週或上週其中一週為紅色時，此條件通過 |

量柱預設以 `Close >= Open` 判定為綠色；`volume_color_mode="prev_close"` 則比較本週 Close 與前週 Close。沒有 Volume 欄位時，成交量檢查不通過。

回傳字典包含整體 `passed`、逐項布林值 `checks`、`ma10`、`ma20`、`body_pct`、`green_volume_weeks` 與最新周標籤 `week`。資料少於 `max(20, volume_lookback + 2)` 週時回傳 `passed=False` 及 `reason`，不會產生完整的逐項結果。

## 在 Stockbot 中的使用方式

`run_agent.py` 的 `evaluate_weekly_signal` 將最近的 Yahoo Finance 日線彙整成周線，計算 Darvas、Squeeze 與周線過濾；監控流程另由 `build_kalman_input` 提供已確認周線給 Kalman 計算，並以當前分鐘報價比較價格位置與價差。實際通知門檻由主流程及 [`AGENTS.md`](../AGENTS.md)、[`rules.md`](../rules.md) 控制，不等同於單獨呼叫任一 `calculate_*` 函式的 `passed` 結果。

主流程會要求至少 40 根周 K，並檢查必要數值及顏色；任何必要資料無效或條件未通過，都會略過通知。指標結果供執行紀錄使用；Telegram 通知的內容另依主流程格式產生。