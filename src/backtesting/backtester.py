"""
Simple Backtester
Simulates trading using model signals on historical data
Compares ML strategy vs Buy-and-Hold benchmark
"""
import pandas as pd
import numpy as np
from loguru import logger


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

        return self._metrics(df)

    def _metrics(self, df: pd.DataFrame) -> dict:
        pv = df["Portfolio_Value"]
        bh = df["BnH_Value"]

        total_return_ml  = (pv.iloc[-1] / self.initial_capital - 1) * 100
        total_return_bnh = (bh.iloc[-1] / self.initial_capital - 1) * 100

        daily_returns = pv.pct_change().dropna()
        sharpe = (daily_returns.mean() / daily_returns.std()) * np.sqrt(252) if daily_returns.std() > 0 else 0

        rolling_max = pv.cummax()
        drawdown = (pv - rolling_max) / rolling_max
        max_drawdown = drawdown.min() * 100

        return {
            "ml_return_pct":    round(total_return_ml, 2),
            "bnh_return_pct":   round(total_return_bnh, 2),
            "sharpe_ratio":     round(sharpe, 3),
            "max_drawdown_pct": round(max_drawdown, 2),
            "final_value":      round(pv.iloc[-1], 2),
            "df":               df
        }
