"""
models/model_loader.py
=============================================================================
Model Inference & Candidate Ranking Engine.
Loads LightGBM models:
- 09:40 Hybrid Rebound-Aware Model
- 09:20 Scalp Model
Enforces Polarity-Safe Scoring Guardrail (PR #10 Forensic Fix):
Ensures that price drops correspond strictly to high Put Option conviction.
=============================================================================
"""

import os
from pathlib import Path
from typing import List, Dict, Optional
import numpy as np
import pandas as pd
import lightgbm as lgb
from config.settings import MODELS_DIR

PURE_DB_FEATURES_0940 = [
    'ret_0915_0940', 'ret_0915_0920', 'ret_0920_0940', 'range_0915_0940',
    'vol_ratio_0940', 'vwap_dist_0940', 'nifty_ret_0940', 'dist_low_0940'
]


class ModelLoader:
    def __init__(self, models_dir: Path = MODELS_DIR):
        self.models_dir = Path(models_dir)
        self.model_0940: Optional[lgb.Booster] = None
        self.model_0920: Optional[lgb.Booster] = None
        self._load_models()

    def _load_models(self):
        """Loads LightGBM booster models from text checkpoints."""
        path_0940 = self.models_dir / "lgb_0940_rebound_aware_audited_model.txt"
        if not path_0940.exists():
            path_0940 = self.models_dir / "lgb_0940_fno_only_rebound_aware_model.txt"

        if path_0940.exists():
            try:
                self.model_0940 = lgb.Booster(model_file=str(path_0940))
            except Exception as e:
                print(f"⚠️ Error loading 09:40 model: {e}")

        path_0920 = self.models_dir / "lgb_0920_scalp_model.txt"
        if path_0920.exists():
            try:
                self.model_0920 = lgb.Booster(model_file=str(path_0920))
            except Exception as e:
                print(f"⚠️ Error loading 09:20 model: {e}")

    def score_candidates_0940(self, df_features: pd.DataFrame) -> pd.DataFrame:
        """
        Infers short conviction scores for 09:40 pipeline using polarity-safe ranking.

        Parameters:
        -----------
        df_features : pd.DataFrame
            Must contain stock identifier and feature columns.

        Returns:
        --------
        pd.DataFrame sorted in descending order of short_conviction.
        """
        if self.model_0940 is None or df_features.empty:
            return df_features

        df = df_features.copy()

        # Dynamic feature alignment using trained booster metadata
        expected_features = self.model_0940.feature_name()
        for col in expected_features:
            if col not in df.columns:
                df[col] = 0.0

        preds = self.model_0940.predict(df[expected_features])
        df['raw_pred'] = preds

        # POLARITY-SAFE SCORING GUARDRAIL (PR #10 FIX):
        # In Options / Short mode: Negative price prediction = deep drop = HIGH short conviction
        # Therefore: short_conviction = -raw_pred
        df['short_conviction'] = -df['raw_pred']

        # Clean percentile rank
        df['conviction_pct'] = df['short_conviction'].rank(pct=True, ascending=True)

        # Sort descending so top candidate is at row index 0
        df_ranked = df.sort_values('short_conviction', ascending=False).reset_index(drop=True)
        return df_ranked

    def score_candidates_0920(self, df_features: pd.DataFrame) -> pd.DataFrame:
        """
        Infers short conviction scores for 09:20 pipeline.
        """
        if self.model_0920 is None or df_features.empty:
            return df_features

        df = df_features.copy()
        expected_features = self.model_0920.feature_name()
        for col in expected_features:
            if col not in df.columns:
                df[col] = 0.0

        preds = self.model_0920.predict(df[expected_features])
        df['raw_pred'] = preds
        df['short_conviction'] = -df['raw_pred']
        df_ranked = df.sort_values('short_conviction', ascending=False).reset_index(drop=True)
        return df_ranked
