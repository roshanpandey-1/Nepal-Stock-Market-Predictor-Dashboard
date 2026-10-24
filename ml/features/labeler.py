"""
Signal Labeler
Creates Buy / Sell / Hold labels from future returns
"""
import pandas as pd

BUY_THRESHOLD  =  0.01   # +1%
SELL_THRESHOLD = -0.01   # -1%

def add_labels(df: pd.DataFrame, horizon: int = 1) -> pd.DataFrame:
    """
    Adds a 'Label' column: 2=Buy, 0=Sell, 1=Hold
    based on next `horizon` day(s) return.
    IMPORTANT: shift(-horizon) — never shuffle before splitting!
    """
    df = df.copy()
    df["Future_Return"] = df["Close"].pct_change(horizon).shift(-horizon)
    df["Label"] = 1  # Hold by default
    df.loc[df["Future_Return"] >  BUY_THRESHOLD,  "Label"] = 2  # Buy
    df.loc[df["Future_Return"] <  SELL_THRESHOLD, "Label"] = 0  # Sell
    return df
