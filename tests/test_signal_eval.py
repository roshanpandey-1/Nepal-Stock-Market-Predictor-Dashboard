import importlib.util
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT))
spec = importlib.util.spec_from_file_location("evaluate_signals_oos", ROOT / "examples" / "evaluate_signals_oos.py")
ev = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ev)


def _total(daily):
    return float(np.prod([1 + x for x in daily]) - 1)


def test_rule_that_never_buys_stays_in_cash_with_no_cost():
    daily, trades = ev.simulate_rule([1, 1, 0, 1], [0.05, -0.03, 0.02, 0.01])
    assert trades == 0 and daily == [0, 0, 0, 0]


def test_round_trip_pays_both_sides_dp_and_tax_on_the_gain():
    # buy before day 1, hold through a +10% move, sold at the end of the window
    daily, trades = ev.simulate_rule([2, 1], [0.10, 0.0])
    eq = (1 - ev.SIDE) * 1.10
    gain = eq - (1 - ev.SIDE)
    expected = eq * (1 - ev.SIDE - ev.DP_SELL) - ev.CGT * gain
    assert trades == 1 and _total(daily) == pytest.approx(expected - 1)


def test_losing_round_trip_pays_no_tax():
    with_tax, _ = ev.simulate_rule([2, 0], [-0.05, 0.0])
    no_tax, _ = ev.simulate_rule([2, 0], [-0.05, 0.0], with_tax=False)
    assert _total(with_tax) == pytest.approx(_total(no_tax))


def test_sell_signal_exits_and_hold_keeps_the_position():
    daily, trades = ev.simulate_rule([2, 1, 0, 1], [0.01, 0.01, 0.05, 0.05])
    assert trades == 1
    assert daily[2] < 0.0 and daily[3] == 0     # out of the market for the +5% days


def test_buy_and_hold_matches_the_rule_buying_on_day_one():
    rets = [0.02, -0.01, 0.03]
    assert ev.buy_and_hold(rets) == ev.simulate_rule([2, 1, 1], rets)[0]


def test_bootstrap_ci_brackets_the_mean_and_is_reproducible():
    x = np.random.default_rng(0).normal(0.001, 0.01, 200)
    m, lo, hi, n = ev.boot_ci(x)
    assert lo < m < hi and n == 200
    assert ev.boot_ci(x) == (m, lo, hi, n)


def test_rank_ic_is_one_for_a_perfect_ranking_and_nan_when_flat():
    assert ev.rank_ic([1, 2, 3, 4, 5], [0.1, 0.2, 0.3, 0.4, 0.5]) == pytest.approx(1.0)
    assert np.isnan(ev.rank_ic([1, 1, 1, 1, 1], [0.1, 0.2, 0.3, 0.4, 0.5]))
    assert np.isnan(ev.rank_ic([1, 2, 3], [0.1, 0.2, 0.3]))   # fewer than 5 tickers
