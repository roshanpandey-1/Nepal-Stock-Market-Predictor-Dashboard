"""
Price Forecaster
Prophet for trend forecasting + LSTM for deep learning
"""
import pandas as pd
import numpy as np
import joblib
from prophet import Prophet
from loguru import logger


class ProphetForecaster:
    def __init__(self):
        self.model = Prophet(
            changepoint_prior_scale=0.05,
            seasonality_prior_scale=10,
            daily_seasonality=False,
            weekly_seasonality=True,
        )

    def train(self, df: pd.DataFrame):
        """df must have 'Date' and 'Close' columns."""
        prophet_df = df[["Date", "Close"]].rename(columns={"Date": "ds", "Close": "y"})
        self.model.fit(prophet_df)
        logger.info("Prophet model trained")

    def forecast(self, days: int = 7) -> pd.DataFrame:
        future = self.model.make_future_dataframe(periods=days)
        forecast = self.model.predict(future)
        return forecast[["ds", "yhat", "yhat_lower", "yhat_upper"]].tail(days)

    def save(self, path: str = "data/models/prophet_model.pkl"):
        joblib.dump(self.model, path)
        logger.info(f"Prophet model saved → {path}")

    @staticmethod
    def load(path: str = "data/models/prophet_model.pkl"):
        obj = ProphetForecaster()
        obj.model = joblib.load(path)
        return obj
