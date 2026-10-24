"""
Tests for ml/backtesting: metrics.py and backtester.py
These stay dependency-light (pure pandas/numpy) so they run without torch/
xgboost installed -- the actual trained models are exercised end-to-end by
scripts/run_backtests_oos.py instead, which does need those.
"""
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parents[1]))

import numpy as np
import pandas as pd
import pytest

from ml.backtesting import metrics


class TestMetrics:
    def test_total_return_pct_simple_gain(self):
        values = pd.Series([100000, 110000, 120000])
        assert metrics.total_return_pct(values, 100000) == pytest.approx(20.0)

    def test_total_return_pct_simple_loss(self):
        values = pd.Series([100000, 90000, 80000])
        assert metrics.total_return_pct(values, 100000) == pytest.approx(-20.0)

    def test_sharpe_ratio_zero_when_flat(self):
        values = pd.Series([100000] * 10)
        assert metrics.sharpe_ratio(values) == 0.0

    def test_sharpe_ratio_positive_for_steady_gains(self):
        values = pd.Series([100000 * (1.001 ** i) for i in range(50)])
        assert metrics.sharpe_ratio(values) > 0

    def test_max_drawdown_pct_is_non_positive(self):
        values = pd.Series([100, 120, 90, 110])
        dd = metrics.max_drawdown_pct(values)
        assert dd <= 0
        # peak 120 -> trough 90 = -25%
        assert dd == pytest.approx(-25.0)

    def test_max_drawdown_pct_zero_for_monotonic_gain(self):
        values = pd.Series([100, 110, 120, 130])
        assert metrics.max_drawdown_pct(values) == pytest.approx(0.0)

    def test_win_rate_pct_empty_trades(self):
        assert metrics.win_rate_pct([]) == 0.0

    def test_win_rate_pct_mixed_trades(self):
        assert metrics.win_rate_pct([10, -5, 20, -1]) == pytest.approx(50.0)

    def test_extract_trade_returns_single_round_trip(self):
        df = pd.DataFrame({
            "Signal": [1, 2, 1, 1, 0],   # Hold, Buy, Hold, Hold, Sell
            "Close":  [100, 100, 105, 108, 110],
        })
        trades = metrics.extract_trade_returns(df)
        assert len(trades) == 1
        assert trades[0] == pytest.approx(10.0)  # 110/100 - 1 = 10%

    def test_extract_trade_returns_no_open_position(self):
        df = pd.DataFrame({"Signal": [1, 1, 1], "Close": [100, 101, 102]})
        assert metrics.extract_trade_returns(df) == []

    def test_summarize_returns_expected_keys(self):
        df = pd.DataFrame({
            "Signal": [1, 2, 1, 0, 1],
            "Close": [100, 100, 105, 110, 110],
            "Portfolio_Value": [100000, 100000, 105000, 110000, 110000],
        })
        result = metrics.summarize(df, initial_capital=100000)
        for key in ["total_return_pct", "sharpe_ratio", "max_drawdown_pct",
                    "win_rate_pct", "num_trades"]:
            assert key in result
        assert result["num_trades"] == 1
