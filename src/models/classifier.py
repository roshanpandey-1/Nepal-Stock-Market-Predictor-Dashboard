"""
Buy/Sell/Hold Signal Classifier
XGBoost + LightGBM with Optuna tuning and SHAP explainability
"""
import pandas as pd
import numpy as np
import shap
import joblib
import optuna
from xgboost import XGBClassifier
from lightgbm import LGBMClassifier
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import classification_report
from loguru import logger

LABEL_MAP = {0: "Sell", 1: "Hold", 2: "Buy"}

class SignalClassifier:
    def __init__(self, model_type: str = "lightgbm"):
        self.model_type = model_type
        self.model = None
        self.explainer = None
        self.feature_cols = None

    def _get_model(self, params=None):
        params = params or {}
        if self.model_type == "xgboost":
            return XGBClassifier(eval_metric="mlogloss", use_label_encoder=False, **params)
        return LGBMClassifier(**params)

    def tune(self, X: pd.DataFrame, y: pd.Series, n_trials: int = 30):
        """Optuna hyperparameter search with TimeSeriesSplit."""
        tscv = TimeSeriesSplit(n_splits=5)

        def objective(trial):
            params = {
                "n_estimators":  trial.suggest_int("n_estimators", 100, 500),
                "max_depth":     trial.suggest_int("max_depth", 3, 8),
                "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.2, log=True),
                "num_leaves":    trial.suggest_int("num_leaves", 20, 60),
            }
            scores = []
            for train_idx, val_idx in tscv.split(X):
                m = self._get_model(params)
                m.fit(X.iloc[train_idx], y.iloc[train_idx])
                scores.append(m.score(X.iloc[val_idx], y.iloc[val_idx]))
            return np.mean(scores)

        study = optuna.create_study(direction="maximize")
        study.optimize(objective, n_trials=n_trials, show_progress_bar=True)
        logger.info(f"Best params: {study.best_params}")
        return study.best_params

    def train(self, X: pd.DataFrame, y: pd.Series, params=None):
        self.feature_cols = X.columns.tolist()
        self.model = self._get_model(params)
        self.model.fit(X, y)
        self.explainer = shap.TreeExplainer(self.model)
        logger.info("Classifier trained successfully")

    def predict(self, X: pd.DataFrame) -> dict:
        pred = self.model.predict(X)[0]
        proba = self.model.predict_proba(X)[0]
        shap_values = self.explainer.shap_values(X)
        return {
            "signal":     LABEL_MAP[pred],
            "confidence": float(max(proba)),
            "probabilities": {LABEL_MAP[i]: float(p) for i, p in enumerate(proba)},
            "shap_values": shap_values[pred][0].tolist() if isinstance(shap_values, list) else shap_values[0].tolist(),
            "feature_names": self.feature_cols
        }

    def evaluate(self, X: pd.DataFrame, y: pd.Series):
        preds = self.model.predict(X)
        print(classification_report(y, preds, target_names=["Sell", "Hold", "Buy"]))

    def save(self, path: str = "data/models/classifier.pkl"):
        joblib.dump(self, path)
        logger.info(f"Classifier saved → {path}")

    @staticmethod
    def load(path: str = "data/models/classifier.pkl"):
        return joblib.load(path)
