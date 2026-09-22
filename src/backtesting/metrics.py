"""
Backtesting Metrics
Standalone, reusable performance metrics for a portfolio value series.
Used by Backtester (src/backtesting/backtester.py) and callable directly
from notebooks or the Flask backtest route.
"""
import numpy as np
import pandas as pd


def total_return_pct(values: pd.Series, initial_capital: float) -> float:
    """Total percentage return from initial_capital to the final value."""
    return (values.iloc[-1] / initial_capital - 1) * 100


def sharpe_ratio(values: pd.Series, periods_per_year: int = 252) -> float:
    """Annualized Sharpe ratio (risk-free rate assumed 0) from a value series."""
    daily_returns = values.pct_change().dropna()
    if daily_returns.std() == 0 or len(daily_returns) == 0:
        return 0.0
    return (daily_returns.mean() / daily_returns.std()) * np.sqrt(periods_per_year)


def max_drawdown_pct(values: pd.Series) -> float:
    """Maximum peak-to-trough decline, as a negative percentage."""
    rolling_max = values.cummax()
    drawdown = (values - rolling_max) / rolling_max
    return drawdown.min() * 100


def win_rate_pct(trade_returns: list) -> float:
    """Percentage of closed trades that were profitable.
    trade_returns: list of per-trade percentage (or absolute) P&L values,
    one entry per completed buy->sell round trip.
    """
    if not trade_returns:
        return 0.0
    wins = sum(1 for r in trade_returns if r > 0)
    return (wins / len(trade_returns)) * 100


def extract_trade_returns(df: pd.DataFrame, signal_col: str = "Signal", price_col: str = "Close") -> list:
    """Walk a signal series and return the pct P&L of each completed Buy->Sell round trip."""
    trades = []
    entry_price = None
    for _, row in df.iterrows():
        signal = row[signal_col]
        price = row[price_col]
        if signal == 2 and entry_price is None:      # Buy: open position
            entry_price = price
        elif signal == 0 and entry_price is not None:  # Sell: close position
            trades.append((price / entry_price - 1) * 100)
            entry_price = None
    return trades


def summarize(df: pd.DataFrame, initial_capital: float, signal_col: str = "Signal",
              portfolio_col: str = "Portfolio_Value") -> dict:
    """One-call summary combining all metrics above, given a df already carrying
    a computed Portfolio_Value column (as produced by Backtester.run)."""
    pv = df[portfolio_col]
    trades = extract_trade_returns(df, signal_col=signal_col)
    return {
        "total_return_pct": round(total_return_pct(pv, initial_capital), 2),
        "sharpe_ratio": round(sharpe_ratio(pv), 3),
        "max_drawdown_pct": round(max_drawdown_pct(pv), 2),
        "win_rate_pct": round(win_rate_pct(trades), 2),
        "num_trades": len(trades),
    }
