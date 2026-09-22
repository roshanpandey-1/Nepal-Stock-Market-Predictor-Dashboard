"""
Tests for src/scraper: NEPSEScraper and NewsScraper.
The underlying `nepse` package and live HTTP calls are mocked -- these tests
check our own column-renaming/parsing logic, not network access or the
third-party API/site itself.
"""
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parents[1]))
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from src.scraper.nepse_scraper import NEPSEScraper


SAMPLE_NEPSE_RESPONSE = {
    "content": [
        {
            "businessDate": "2026-09-20",
            "highPrice": 510.0,
            "lowPrice": 495.0,
            "closePrice": 500.0,
            "totalTradedQuantity": 12345,
            "totalTrades": 88,
            "totalTradedValue": 6172500.0,
        },
        {
            "businessDate": "2026-09-19",
            "highPrice": 500.0,
            "lowPrice": 480.0,
            "closePrice": 495.0,
            "totalTradedQuantity": 9876,
            "totalTrades": 70,
            "totalTradedValue": 4888620.0,
        },
    ]
}


class TestNEPSEScraper:
    @patch("src.scraper.nepse_scraper.Nepse")
    def test_fetch_stock_history_renames_columns(self, mock_nepse_cls):
        mock_instance = MagicMock()
        mock_instance.getCompanyPriceVolumeHistory.return_value = SAMPLE_NEPSE_RESPONSE
        mock_nepse_cls.return_value = mock_instance

        scraper = NEPSEScraper()
        df = scraper.fetch_stock_history("HDL")

        for col in ["Date", "High", "Low", "Close", "Volume", "Trades", "Turnover", "Ticker"]:
            assert col in df.columns

    @patch("src.scraper.nepse_scraper.Nepse")
    def test_fetch_stock_history_sorts_by_date_ascending(self, mock_nepse_cls):
        mock_instance = MagicMock()
        mock_instance.getCompanyPriceVolumeHistory.return_value = SAMPLE_NEPSE_RESPONSE
        mock_nepse_cls.return_value = mock_instance

        scraper = NEPSEScraper()
        df = scraper.fetch_stock_history("HDL")

        assert df["Date"].is_monotonic_increasing

    @patch("src.scraper.nepse_scraper.Nepse")
    def test_fetch_stock_history_tags_ticker(self, mock_nepse_cls):
        mock_instance = MagicMock()
        mock_instance.getCompanyPriceVolumeHistory.return_value = SAMPLE_NEPSE_RESPONSE
        mock_nepse_cls.return_value = mock_instance

        scraper = NEPSEScraper()
        df = scraper.fetch_stock_history("HDL")

        assert (df["Ticker"] == "HDL").all()

    @patch("src.scraper.nepse_scraper.Nepse")
    def test_fetch_stock_history_returns_empty_df_on_error(self, mock_nepse_cls):
        mock_instance = MagicMock()
        mock_instance.getCompanyPriceVolumeHistory.side_effect = Exception("network error")
        mock_nepse_cls.return_value = mock_instance

        scraper = NEPSEScraper()
        df = scraper.fetch_stock_history("BADTICKER")

        assert isinstance(df, pd.DataFrame)
        assert df.empty
