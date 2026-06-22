"""
Technical Indicator Feature Engineering
Uses the `ta` library to compute standard trading indicators
"""
import pandas as pd
import ta
from loguru import logger


class TechnicalIndicators:
    def add_all(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add all technical indicators to a stock OHLCV DataFrame."""
        df = df.copy()
        close = df["Close"]
        high  = df["High"]
        low   = df["Low"]
        vol   = df["Volume"]

        # Trend
        df["SMA_7"]  = ta.trend.sma_indicator(close, window=7)
        df["SMA_21"] = ta.trend.sma_indicator(close, window=21)
        df["SMA_50"] = ta.trend.sma_indicator(close, window=50)
        df["EMA_12"] = ta.trend.ema_indicator(close, window=12)
        df["EMA_26"] = ta.trend.ema_indicator(close, window=26)
        df["MACD"]   = ta.trend.macd(close)
        df["MACD_Signal"] = ta.trend.macd_signal(close)

        # Momentum
        df["RSI_14"] = ta.momentum.rsi(close, window=14)
        df["Stoch"]  = ta.momentum.stoch(high, low, close)

        # Volatility
        bb = ta.volatility.BollingerBands(close)
        df["BB_High"]  = bb.bollinger_hband()
        df["BB_Low"]   = bb.bollinger_lband()
        df["BB_Width"] = bb.bollinger_wband()
        df["ATR"]      = ta.volatility.average_true_range(high, low, close)

        # Volume
        df["Volume_Change"] = vol.pct_change()
        df["OBV"] = ta.volume.on_balance_volume(close, vol)

        # Lag features
        for lag in [1, 3, 5, 10]:
            df[f"Close_lag_{lag}"] = close.shift(lag)
            df[f"Return_lag_{lag}"] = close.pct_change(lag)

        logger.info(f"Added {len([c for c in df.columns if c not in ['Date','Open','High','Low','Close','Volume','Ticker']])} features")
        return df
