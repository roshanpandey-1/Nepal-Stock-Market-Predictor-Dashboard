import sys
sys.path.append('.')
from src.models.forecaster import StockForecaster

forecaster = StockForecaster()

for ticker in ['NABIL', 'AKPL', 'HBL', 'UPPER']:
    result = forecaster.train(ticker, periods=30)
    if result:
        print(f"{ticker}: NPR {result['current_price']} → NPR {result['forecast_price']} ({result['change_pct']}%)")