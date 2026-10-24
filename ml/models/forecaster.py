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

# Production forecast recipe, shared with scripts/validate_forecasts.py so the
# accuracy check always tests exactly what the weekly forecast job runs.
#
# Chosen by that check (2026-10-24, 260 stocks, 5 past start dates): fitting the
# full history since 2011 with yearly seasonality gave a 30-day error of about
# 18%, against 5.6% for simply assuming the price stays put. Fitting only the last
# 2 years and starting the forecast from the last close ("anchored") cut that to
# 7.3% and made the 80% range roughly honest (72% coverage) -- but it still does
# not beat "no change", and its up/down call is right less than half the time.
# So the dashboard presents it as a range of likely prices, not a prediction.
#
# weekly_seasonality is off: NEPSE traded Sunday-Thursday until April 2026 and
# Monday-Friday since, so almost every Friday in the history is a non-trading day,
# and a weekly term forecasts a fake ~7% drop every Friday.
PROPHET_PARAMS = dict(
    daily_seasonality=False,
    weekly_seasonality=False,
    yearly_seasonality=False,
    changepoint_prior_scale=0.05,
)
TRAIN_YEARS = 2


def fit_and_forecast(history: pd.DataFrame, future_dates) -> pd.DataFrame:
    """Fit the production recipe on ``history`` (Date, Close) and forecast ``future_dates``.

    Returns ds, yhat, yhat_lower, yhat_upper, shifted so the forecast starts from
    the last close rather than from Prophet's fitted level.
    """
    history = history.dropna(subset=['Close']).drop_duplicates('Date').sort_values('Date')
    last_date = history['Date'].iloc[-1]
    train = history[history['Date'] >= last_date - pd.DateOffset(years=TRAIN_YEARS)]
    model = Prophet(**PROPHET_PARAMS)
    model.fit(train[['Date', 'Close']].rename(columns={'Date': 'ds', 'Close': 'y'}))
    fc = model.predict(pd.DataFrame({'ds': pd.to_datetime(list(future_dates))}))
    fitted_now = float(model.predict(pd.DataFrame({'ds': [last_date]}))['yhat'].iloc[0])
    shift = float(train['Close'].iloc[-1]) - fitted_now
    fc[['yhat', 'yhat_lower', 'yhat_upper']] += shift
    return fc[['ds', 'yhat', 'yhat_lower', 'yhat_upper']]


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

        last_date = df['Date'].iloc[-1]
        future_dates = pd.bdate_range(last_date + pd.Timedelta(days=1), periods=periods)
        self.forecast = fit_and_forecast(df[['Date', 'Close']], future_dates)

        # Extract key metrics
        current_price = df['Close'].iloc[-1]
        future_only = self.forecast

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