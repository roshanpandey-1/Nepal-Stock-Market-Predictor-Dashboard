"""
Prophet Price Forecaster
Forecasts future stock prices for any NEPSE ticker
"""
import pandas as pd
import numpy as np
from prophet import Prophet
import plotly.graph_objects as go
import warnings
warnings.filterwarnings('ignore')
from loguru import logger


class StockForecaster:
    def __init__(self):
        self.model = None
        self.forecast = None
        self.ticker = None

    def load_data(self, ticker: str) -> pd.DataFrame:
        """Load stock data for a given ticker"""
        try:
            df = pd.read_csv(f'data/raw/{ticker}.csv')
            df['Date'] = pd.to_datetime(df['Date'])
            df = df.sort_values('Date').reset_index(drop=True)
            logger.info(f"{ticker}: Loaded {len(df)} rows")
            return df
        except FileNotFoundError:
            logger.error(f"{ticker}: File not found")
            return pd.DataFrame()

    def train(self, ticker: str, periods: int = 30) -> dict:
        """Train Prophet and generate forecast"""
        self.ticker = ticker

        df = self.load_data(ticker)
        if df.empty:
            return {}

        # Prepare for Prophet
        prophet_df = df[['Date', 'Close']].rename(
            columns={'Date': 'ds', 'Close': 'y'}
        )

        # Train Prophet
        self.model = Prophet(
            daily_seasonality=False,
            weekly_seasonality=True,
            yearly_seasonality=True,
            changepoint_prior_scale=0.05
        )
        self.model.fit(prophet_df)

        # Forecast
        future = self.model.make_future_dataframe(periods=periods, freq='B')
        self.forecast = self.model.predict(future)

        # Extract key metrics
        current_price = df['Close'].iloc[-1]
        future_only = self.forecast[self.forecast['ds'] > prophet_df['ds'].max()]

        result = {
            'ticker': ticker,
            'current_price': round(current_price, 2),
            'forecast_price': round(future_only['yhat'].iloc[-1], 2),
            'lower_bound': round(future_only['yhat_lower'].iloc[-1], 2),
            'upper_bound': round(future_only['yhat_upper'].iloc[-1], 2),
            'change_pct': round(
                (future_only['yhat'].iloc[-1] - current_price) / current_price * 100, 2
            ),
            'forecast_df': future_only[['ds', 'yhat', 'yhat_lower', 'yhat_upper']]
        }

        logger.info(f"{ticker}: Current={current_price} | Forecast={result['forecast_price']} | Change={result['change_pct']}%")
        return result

    def plot(self, days_history: int = 180) -> go.Figure:
        """Generate interactive Plotly forecast chart"""
        if self.forecast is None:
            logger.error("No forecast available — run train() first")
            return None

        df = self.load_data(self.ticker)
        prophet_df = df[['Date', 'Close']].rename(
            columns={'Date': 'ds', 'Close': 'y'}
        )

        cutoff = prophet_df['ds'].max() - pd.Timedelta(days=days_history)
        recent = prophet_df[prophet_df['ds'] >= cutoff]
        future_only = self.forecast[self.forecast['ds'] > prophet_df['ds'].max()]

        fig = go.Figure()

        # Actual price
        fig.add_trace(go.Scatter(
            x=recent['ds'],
            y=recent['y'],
            name='Actual Price',
            line=dict(color='steelblue', width=2),
            hovertemplate='<b>Date:</b> %{x|%Y-%m-%d}<br><b>Price:</b> NPR %{y:.1f}<extra></extra>'
        ))

        # Forecast
        fig.add_trace(go.Scatter(
            x=future_only['ds'],
            y=future_only['yhat'],
            name='Forecast',
            line=dict(color='red', width=2, dash='dash'),
            hovertemplate='<b>Date:</b> %{x|%Y-%m-%d}<br><b>Forecast:</b> NPR %{y:.1f}<extra></extra>'
        ))

        # Upper bound
        fig.add_trace(go.Scatter(
            x=future_only['ds'],
            y=future_only['yhat_upper'],
            name='Upper Bound',
            line=dict(width=0),
            showlegend=False,
            hovertemplate='<b>Upper:</b> NPR %{y:.1f}<extra></extra>'
        ))

        # Lower bound with fill
        fig.add_trace(go.Scatter(
            x=future_only['ds'],
            y=future_only['yhat_lower'],
            name='Confidence Interval',
            line=dict(width=0),
            fill='tonexty',
            fillcolor='rgba(255,0,0,0.15)',
            hovertemplate='<b>Lower:</b> NPR %{y:.1f}<extra></extra>'
        ))

        fig.update_layout(
            title=f'{self.ticker} — Price Forecast (Next 30 Days)',
            xaxis_title='Date',
            yaxis_title='Price (NPR)',
            hovermode='x unified',
            template='plotly_white',
            height=500,
            legend=dict(orientation='h', yanchor='bottom', y=1.02),
            xaxis=dict(
                rangeslider=dict(visible=True),
                rangeselector=dict(
                    buttons=list([
                        dict(count=7,  label='1W', step='day',   stepmode='backward'),
                        dict(count=1,  label='1M', step='month', stepmode='backward'),
                        dict(count=3,  label='3M', step='month', stepmode='backward'),
                        dict(count=6,  label='6M', step='month', stepmode='backward'),
                        dict(step='all', label='All')
                    ])
                )
            )
        )

        return fig


# ── Test ─────────────────────────────────────────────────────
if __name__ == '__main__':
    forecaster = StockForecaster()
    result = forecaster.train('NABIL', periods=30)

    print(f"\nTicker: {result['ticker']}")
    print(f"Current Price: NPR {result['current_price']}")
    print(f"30-Day Forecast: NPR {result['forecast_price']}")
    print(f"Change: {result['change_pct']}%")
    print(f"Range: NPR {result['lower_bound']} - NPR {result['upper_bound']}")