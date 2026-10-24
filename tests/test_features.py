"""
Tests for ml/features: technical_indicators.py and labeler.py
"""
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parents[1]))

import numpy as np
import pandas as pd
import pytest

from ml.features.technical_indicators import TechnicalIndicators
from ml.features.labeler import add_labels, BUY_THRESHOLD, SELL_THRESHOLD


def make_synthetic_ohlcv(n=120, seed=42):
    """A synthetic-but-plausible OHLCV series, long enough for a 50-day SMA."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    close = 100 + np.cumsum(rng.normal(0, 1, n))
    close = np.clip(close, 10, None)  # keep prices positive
    high = close + rng.uniform(0, 2, n)
    low = close - rng.uniform(0, 2, n)
    open_ = close + rng.uniform(-1, 1, n)
    volume = rng.integers(1000, 50000, n)
    return pd.DataFrame({
        "Date": dates, "Open": open_, "High": high, "Low": low,
        "Close": close, "Volume": volume,
    })


class TestTechnicalIndicators:
    def test_add_all_adds_expected_columns(self):
        df = make_synthetic_ohlcv()
        ti = TechnicalIndicators()
        out = ti.add_all(df)
        for col in ["SMA_7", "SMA_21", "SMA_50", "EMA_12", "EMA_26", "MACD",
                    "RSI_14", "BB_High", "BB_Low", "ATR", "OBV",
                    "Close_lag_1", "Return_lag_1"]:
            assert col in out.columns, f"missing expected feature column: {col}"

    def test_add_all_preserves_row_count(self):
        df = make_synthetic_ohlcv()
        ti = TechnicalIndicators()
        out = ti.add_all(df)
        assert len(out) == len(df)

    def test_rsi_stays_within_bounds(self):
        df = make_synthetic_ohlcv()
        ti = TechnicalIndicators()
        out = ti.add_all(df)
        rsi = out["RSI_14"].dropna()
        assert (rsi >= 0).all() and (rsi <= 100).all()


class TestLabeler:
    def test_buy_label_on_strong_positive_return(self):
        df = pd.DataFrame({"Close": [100, 100 * (1 + BUY_THRESHOLD + 0.01)]})
        out = add_labels(df, horizon=1)
        assert out["Label"].iloc[0] == 2  # Buy

    def test_sell_label_on_strong_negative_return(self):
        df = pd.DataFrame({"Close": [100, 100 * (1 + SELL_THRESHOLD - 0.01)]})
        out = add_labels(df, horizon=1)
        assert out["Label"].iloc[0] == 0  # Sell

    def test_hold_label_on_flat_return(self):
        df = pd.DataFrame({"Close": [100, 100.1]})
        out = add_labels(df, horizon=1)
        assert out["Label"].iloc[0] == 1  # Hold

    def test_last_row_has_no_future_return(self):
        df = pd.DataFrame({"Close": [100, 101, 102]})
        out = add_labels(df, horizon=1)
        assert pd.isna(out["Future_Return"].iloc[-1])

    def test_labels_are_only_0_1_2(self):
        df = make_synthetic_ohlcv()
        out = add_labels(df, horizon=1)
        assert set(out["Label"].unique()).issubset({0, 1, 2})
