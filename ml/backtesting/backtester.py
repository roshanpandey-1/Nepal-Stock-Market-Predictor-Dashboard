"""
Simple Backtester
Simulates trading using model signals on historical data
Compares ML strategy vs Buy-and-Hold benchmark
"""
import pandas as pd
from loguru import logger

from . import metrics


class Backtester:
    def __init__(self, initial_capital: float = 100000):
        self.initial_capital = initial_capital

    def run(self, df: pd.DataFrame, signal_col: str = "Signal") -> dict:
        """
        df must have: Date, Close, Signal (2=Buy, 1=Hold, 0=Sell)
        Returns performance metrics dict.
        """
        df = df.copy().sort_values("Date").reset_index(drop=True)
        capital = self.initial_capital
        position = 0  # shares held
        portfolio_values = []

        for i, row in df.iterrows():
            price = row["Close"]
            signal = row[signal_col]

            if signal == 2 and position == 0:   # Buy
                position = capital / price
                capital = 0
            elif signal == 0 and position > 0:  # Sell
                capital = position * price
                position = 0

            portfolio_values.append(capital + position * price)

        df["Portfolio_Value"] = portfolio_values
        df["BnH_Value"] = self.initial_capital * (df["Close"] / df["Close"].iloc[0])

        return self._metrics(df, signal_col)

    def _metrics(self, df: pd.DataFrame, signal_col: str) -> dict:
        pv = df["Portfolio_Value"]
        bh = df["BnH_Value"]

        summary = metrics.summarize(df, self.initial_capital, signal_col=signal_col)

        return {
            "ml_return_pct":    summary["total_return_pct"],
            "bnh_return_pct":   round(metrics.total_return_pct(bh, self.initial_capital), 2),
            "sharpe_ratio":     summary["sharpe_ratio"],
            "max_drawdown_pct": summary["max_drawdown_pct"],
            "win_rate_pct":     summary["win_rate_pct"],
            "num_trades":       summary["num_trades"],
            "final_value":      round(pv.iloc[-1], 2),
            "df":               df
        }
