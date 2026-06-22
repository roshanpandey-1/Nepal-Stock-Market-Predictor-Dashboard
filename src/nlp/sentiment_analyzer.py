"""
Sentiment Analyzer
Uses HuggingFace multilingual model to score financial news headlines
"""
import pandas as pd
from transformers import pipeline
from loguru import logger


class SentimentAnalyzer:
    def __init__(self, model: str = "cardiffnlp/twitter-xlm-roberta-base-sentiment"):
        """
        Default model supports multilingual text including Nepali-English mixed.
        Alternative: 'ProsusAI/finbert' for English financial text.
        """
        logger.info(f"Loading sentiment model: {model}")
        self.pipe = pipeline("sentiment-analysis", model=model, truncation=True, max_length=512)

    def score(self, texts: list) -> list:
        """Returns list of dicts: {label, score} for each text."""
        results = []
        for text in texts:
            try:
                out = self.pipe(text[:512])[0]
                label = out["label"].lower()
                score = out["score"]
                # Normalize to -1 (negative) to +1 (positive)
                if "neg" in label:
                    normalized = -score
                elif "pos" in label:
                    normalized = score
                else:
                    normalized = 0.0
                results.append({"label": label, "score": score, "normalized": normalized})
            except Exception as e:
                logger.warning(f"Sentiment error: {e}")
                results.append({"label": "neutral", "score": 0.5, "normalized": 0.0})
        return results

    def score_dataframe(self, df: pd.DataFrame, text_col: str = "title") -> pd.DataFrame:
        df = df.copy()
        scores = self.score(df[text_col].tolist())
        df["sentiment_label"]      = [s["label"] for s in scores]
        df["sentiment_score"]      = [s["score"] for s in scores]
        df["sentiment_normalized"] = [s["normalized"] for s in scores]
        return df
