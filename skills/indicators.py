"""技術指標 Skill：Darvas Box / Squeeze Momentum / Adaptive Kalman Trend / 周線過濾。

所有函數都接受 OHLCV DataFrame（DatetimeIndex，欄位 Open/High/Low/Close/Volume，
大小寫皆可，例如 yfinance 的 history() 輸出）。

每個指標都有兩層：
    *_series(df)      回傳整段序列（回測、畫圖用）
    calculate_*(df)   回傳最新一根 K 棒的狀態 dict（盯盤用）

「寧可漏報」原則：資料不足時，狀態欄位為 None / passed=False，並附上 reason。
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view

OHLCV = ("Open", "High", "Low", "Close", "Volume")


# ---------------------------------------------------------------------------
# 共用工具
# ---------------------------------------------------------------------------

def normalize_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    rename = {c: c.capitalize() for c in df.columns if isinstance(c, str) and c.capitalize() in OHLCV}
    out = df.rename(columns=rename)
    missing = [c for c in ("Open", "High", "Low", "Close") if c not in out.columns]
    if missing:
        raise ValueError(f"DataFrame 缺少欄位: {missing}")
    if not isinstance(out.index, pd.DatetimeIndex):
        raise ValueError("DataFrame index 必須是 DatetimeIndex")
    return out.sort_index()


def is_weekly(df: pd.DataFrame) -> bool:
    if len(df) < 2:
        return False
    return df.index.to_series().diff().median() >= pd.Timedelta(days=5)


def to_weekly(df: pd.DataFrame, rule: str = "W-FRI") -> pd.DataFrame:
    """日線轉周線（已是周線則原樣回傳）。最後一根為當週（可能尚未收完）。"""
    df = normalize_ohlcv(df)
    if is_weekly(df):
        return df
    agg = {"Open": "first", "High": "max", "Low": "min", "Close": "last"}
    if "Volume" in df.columns:
        agg["Volume"] = "sum"
    return df.resample(rule).agg(agg).dropna(subset=["Close"])


def _barssince(cond: pd.Series) -> pd.Series:
    """Pine ta.barssince：距離上次 cond 為 True 的 bar 數，從未發生則 NaN。"""
    idx = np.arange(len(cond), dtype=float)
    last = pd.Series(np.where(cond.to_numpy(bool), idx, np.nan), index=cond.index).ffill()
    return idx - last


def _linreg(s: pd.Series, length: int, offset: int = 0) -> pd.Series:
    """Pine linreg(source, length, offset)：最小平方回歸線在 (length-1-offset) 的值。"""
    arr = s.to_numpy(float)
    out = np.full(len(arr), np.nan)
    if len(arr) >= length:
        w = sliding_window_view(arr, length)
        x = np.arange(length, dtype=float)
        xm = x.mean()
        ym = w.mean(axis=1)
        slope = ((x - xm) * (w - ym[:, None])).sum(axis=1) / ((x - xm) ** 2).sum()
        out[length - 1:] = ym + slope * (length - 1 - offset - xm)
    return pd.Series(out, index=s.index)


def _wma(arr: np.ndarray, length: int) -> np.ndarray:
    """Pine ta.wma：權重 1..length，最新一根權重最大；視窗內有 NaN 則為 NaN。"""
    out = np.full(len(arr), np.nan)
    if len(arr) >= length:
        weights = np.arange(1, length + 1, dtype=float)
        out[length - 1:] = sliding_window_view(arr, length) @ weights / weights.sum()
    return out


def _true_range(df: pd.DataFrame) -> pd.Series:
    prev_close = df["Close"].shift(1)
    return pd.concat(
        [df["High"] - df["Low"], (df["High"] - prev_close).abs(), (df["Low"] - prev_close).abs()],
        axis=1,
    ).max(axis=1, skipna=False)


# ---------------------------------------------------------------------------
# 1. Darvas Box
# ---------------------------------------------------------------------------

def darvas_box_series(df: pd.DataFrame, boxp: int = 5) -> pd.DataFrame:
    """對應 Darvas box.pine 的 TopBox / BottomBox 計算。

    Pine:
        LL = lowest(low, boxp); k1/k2/k3 = highest(high, boxp / boxp-1 / boxp-2)
        NH = valuewhen(high > k1[1], high, 0)
        box1 = k3 < k2
        TopBox    = valuewhen(barssince(high > k1[1]) == boxp-2 and box1, NH, 0)
        BottomBox = valuewhen(barssince(high > k1[1]) == boxp-2 and box1, LL, 0)
        color = close > top ? green : close < bottom ? red : yellow
    """
    if boxp < 3:
        raise ValueError("boxp 必須 >= 3")
    df = normalize_ohlcv(df)
    high, low, close = df["High"], df["Low"], df["Close"]

    ll = low.rolling(boxp).min()
    k1 = high.rolling(boxp).max()
    k2 = high.rolling(boxp - 1).max()
    k3 = high.rolling(boxp - 2).max()

    new_high = high > k1.shift(1)
    nh = high.where(new_high).ffill()
    box_cond = (_barssince(new_high) == boxp - 2) & (k3 < k2)

    top = nh.where(box_cond).ffill()
    bottom = ll.where(box_cond).ffill()

    color = pd.Series(np.where(close > top, "green", np.where(close < bottom, "red", "yellow")),
                      index=df.index, dtype=object)
    color[top.isna() | bottom.isna()] = None
    return pd.DataFrame({"top": top, "bottom": bottom, "color": color, "is_red": color == "red"})


def calculate_darvas_box(df: pd.DataFrame, boxp: int = 5) -> dict:
    """回傳最新 K 棒的 Darvas Box 狀態；收盤跌破 Box 底部（紅色）時 is_red=True。"""
    s = darvas_box_series(df, boxp)
    last = s.iloc[-1]
    if last["color"] is None:
        return {"upper": None, "lower": None, "color": None, "is_red": None, "reason": "資料不足，尚未形成 Box"}
    return {
        "upper": float(last["top"]),
        "lower": float(last["bottom"]),
        "color": last["color"],
        "is_red": bool(last["is_red"]),
    }


# ---------------------------------------------------------------------------
# 2. Squeeze Momentum [LazyBear]
# ---------------------------------------------------------------------------

def squeeze_momentum_series(df: pd.DataFrame, length: int = 20, mult: float = 2.0,
                            length_kc: int = 20, mult_kc: float = 1.5,
                            use_true_range: bool = True) -> pd.DataFrame:
    """重構 LazyBear SQZMOM。

    註：原 Pine 腳本的 BB 標準差誤用 multKC（dev = multKC * stdev），
    此處依需求使用 BB(20, 2.0)；若要與 TradingView 原圖的 squeeze 點完全一致，傳入 mult=1.5。
    mult 只影響 squeeze on/off，不影響直方圖 val 與顏色。
    """
    df = normalize_ohlcv(df)
    high, low, close = df["High"], df["Low"], df["Close"]

    basis = close.rolling(length).mean()
    dev = mult * close.rolling(length).std(ddof=0)  # Pine stdev 為母體標準差
    upper_bb, lower_bb = basis + dev, basis - dev

    ma = close.rolling(length_kc).mean()
    rng = _true_range(df) if use_true_range else (high - low)
    rangema = rng.rolling(length_kc).mean()
    upper_kc, lower_kc = ma + rangema * mult_kc, ma - rangema * mult_kc

    sqz_on = (lower_bb > lower_kc) & (upper_bb < upper_kc)
    sqz_off = (lower_bb < lower_kc) & (upper_bb > upper_kc)
    squeeze = np.where(sqz_on, "on", np.where(sqz_off, "off", "none"))

    mid = ((high.rolling(length_kc).max() + low.rolling(length_kc).min()) / 2 + ma) / 2
    val = _linreg(close - mid, length_kc, 0)

    prev = val.shift(1).fillna(0.0)  # nz(val[1])
    color = pd.Series(
        np.where(val > 0, np.where(val > prev, "lime", "green"),
                 np.where(val < prev, "red", "maroon")),
        index=df.index, dtype=object,
    )
    color[val.isna()] = None

    return pd.DataFrame({
        "val": val, "color": color, "squeeze": squeeze,
        "upper_bb": upper_bb, "lower_bb": lower_bb, "upper_kc": upper_kc, "lower_kc": lower_kc,
    })


def calculate_squeeze_momentum(df: pd.DataFrame, **kwargs) -> dict:
    """回傳最新直方圖狀態。

    passed = True  → 直方圖為 lime / green / maroon（非「持續走弱的 red」）
    is_red = True  → 直方圖為 red（val <= 0 且仍在下降）
    """
    s = squeeze_momentum_series(df, **kwargs)
    last = s.iloc[-1]
    if last["color"] is None:
        return {"val": None, "color": None, "is_red": None, "passed": False, "squeeze": None,
                "reason": "資料不足"}
    return {
        "val": float(last["val"]),
        "color": last["color"],
        "is_red": last["color"] == "red",
        "passed": last["color"] in ("lime", "green", "maroon"),
        "squeeze": last["squeeze"],
    }


# ---------------------------------------------------------------------------
# 3. Adaptive Kalman filter - Trend Strength Oscillator (Zeiierman)
# ---------------------------------------------------------------------------

def kalman_trend_series(df: pd.DataFrame, process_noise_1: float = 0.01, process_noise_2: float = 0.01,
                        measurement_noise: float = 500.0, osc_smooth: int = 10,
                        trend_lookback: int = 10, strength_smooth: int = 10,
                        model: str = "standard", mintick: float = 0.01) -> pd.DataFrame:
    """逐根重現 Zeiierman Pine 腳本（輸入的時間框架即為計算框架）。

    忠實保留原腳本行為：
      - 每根 bar 預測前重設 P 的對角線為 1，非對角線延續前一根狀態
      - 預測步驟 x2 = F[1,1] * X[1] = 0
    model: "standard" | "volume_adjusted" | "parkinson_adjusted"
    """
    df = normalize_ohlcv(df)
    src = df["Close"].to_numpy(float)
    high = df["High"].to_numpy(float)
    low = df["Low"].to_numpy(float)
    vol = df["Volume"].to_numpy(float) if "Volume" in df.columns else None
    if model == "volume_adjusted" and vol is None:
        raise ValueError("volume_adjusted 模型需要 Volume 欄位")

    n = len(src)
    F = np.array([[1.0, 1.0], [1.0, 0.0]])
    Q = np.array([[process_noise_1, process_noise_1 * process_noise_2],
                  [process_noise_2 * process_noise_1, process_noise_2]])
    H = np.array([[1.0, 0.0]])
    I2 = np.eye(2)
    P = np.eye(2)

    estimate = np.full(n, np.nan)
    raw_strength = np.full(n, np.nan)
    osc_buffer: list[float] = []
    X = np.array([src[0], src[0]]) if n else np.zeros(2)

    for i in range(n):
        P[0, 0] = 1.0
        P[1, 1] = 1.0
        X = np.array([F[0, 0] * X[0] + F[0, 1] * X[1], F[1, 1] * X[1]])
        P = F @ P @ F.T + Q

        r = measurement_noise
        if model != "standard" and i > 2:
            if model == "volume_adjusted":
                denom = min(vol[i - 1], vol[i])
                r = r * vol[i - 1] / denom if denom > 0 else np.nan
            elif model == "parkinson_adjusted":
                r = r * (1 + (high[i] - low[i]) / max(high[i - 1] - low[i - 1], mintick))

        S = (H @ P @ H.T)[0, 0] + r
        K = (P @ H.T) / S
        innovation = src[i] - X[0]
        X = X + K[:, 0] * innovation
        P = (I2 - K @ H) @ P

        estimate[i] = X[0]
        osc_buffer.append(X[1])
        if len(osc_buffer) >= trend_lookback:
            a = max(abs(v) for v in osc_buffer)
            raw_strength[i] = X[1] / a * 100 if a > 0 else np.nan
            osc_buffer.pop(0)

    trend_strength = _wma(raw_strength, strength_smooth)
    oscillator = _wma(trend_strength, osc_smooth)

    # 原腳本配色：|strength| 至少填滿 1 格(每格 10) 才上色，>0 綠(lime)、<0 紅，否則藍
    segments = np.floor(np.abs(trend_strength) / 10)
    color = np.where(np.isnan(trend_strength) | (segments < 1), "blue",
                     np.where(trend_strength > 0, "green", "red"))

    return pd.DataFrame({
        "kalman": estimate, "trend_strength": trend_strength,
        "oscillator": oscillator, "color": color,
    }, index=df.index)


def calculate_kalman_trend(df: pd.DataFrame, weekly: bool = True,
                           include_current_bar: bool = True, **kwargs) -> dict:
    """周線 Kalman 趨勢強度；is_green=True 代表當周為綠線（trend_strength >= 10）。

    include_current_bar=False 時只看已收完的上一根周 K，與 TradingView
    (barstate.isconfirmed) 在盤中顯示的一致。
    """
    data = to_weekly(df) if weekly else normalize_ohlcv(df)
    if not include_current_bar:
        data = data.iloc[:-1]
    s = kalman_trend_series(data, **kwargs)
    if s.empty or pd.isna(s["trend_strength"].iloc[-1]):
        return {"trend_strength": None, "oscillator": None, "kalman": None, "color": None,
                "is_green": False, "reason": "資料不足"}
    last = s.iloc[-1]
    osc = last["oscillator"]
    return {
        "trend_strength": float(last["trend_strength"]),
        "oscillator": None if pd.isna(osc) else float(osc),
        "kalman": float(last["kalman"]),
        "color": last["color"],
        "is_green": last["color"] == "green",
        "as_of": s.index[-1],
    }


# ---------------------------------------------------------------------------
# 4. 周線技能過濾
# ---------------------------------------------------------------------------

def calculate_weekly_filters(df: pd.DataFrame, doji_max_pct: float = 8.0, doji_mode: str = "open",
                             volume_lookback: int = 6, min_green_volume: int = 3,
                             volume_color_mode: str = "open") -> dict:
    """周線技能過濾，全部通過時 passed=True。

    - ma_trend       : MA10 > MA20（周收盤 SMA）
    - doji           : 當週 |Close-Open| 佔比 <= doji_max_pct
                       doji_mode="open"  → 除以 Open（實體漲跌幅）
                       doji_mode="range" → 除以 High-Low（實體佔整根 K 棒比例）
    - volume_green   : 過去 volume_lookback 週（不含本週）至少 min_green_volume 週量柱為綠
                       volume_color_mode="open"       → Close >= Open 為綠（TradingView 預設）
                       volume_color_mode="prev_close" → Close >= 前週 Close 為綠
    - not_consecutive_red_volume : 本週與上週不得同時為紅色；單週紅色不影響此條件
    """
    w = to_weekly(df)
    need = max(20, volume_lookback + 2)
    if len(w) < need:
        return {"passed": False, "reason": f"周線資料不足（{len(w)} < {need} 週）"}

    close, open_ = w["Close"], w["Open"]
    ma10 = close.rolling(10).mean().iloc[-1]
    ma20 = close.rolling(20).mean().iloc[-1]

    o, c, h, l = (float(w[k].iloc[-1]) for k in ("Open", "Close", "High", "Low"))
    if doji_mode == "range":
        body_pct = abs(c - o) / (h - l) * 100 if h > l else 0.0
    else:
        body_pct = abs(c - o) / o * 100

    if "Volume" not in w.columns:
        green_count, volume_ok = None, False
        consecutive_red_ok = False
    else:
        volume_color_reference = open_ if volume_color_mode == "open" else close.shift(1)
        is_green = close >= volume_color_reference
        window = is_green.iloc[-(volume_lookback + 1):-1]
        green_count = int(window.sum())
        volume_ok = green_count >= min_green_volume
        consecutive_red_ok = not bool((~is_green.iloc[-2:]).all())

    checks = {
        "ma_trend": bool(ma10 > ma20),
        "doji": body_pct <= doji_max_pct,
        "volume_green": volume_ok,
        "not_consecutive_red_volume": consecutive_red_ok,
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "ma10": float(ma10),
        "ma20": float(ma20),
        "body_pct": float(body_pct),
        "green_volume_weeks": green_count,
        "week": w.index[-1],
    }
