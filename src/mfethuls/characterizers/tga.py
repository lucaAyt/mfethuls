import logging

import pandas as pd

logger = logging.getLogger(__name__)


class TGACharacterizer:
    def characterize(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df

        if "mass_pct" in df.columns and df["mass_pct"].notna().all():
            return df

        if "mass_mg" not in df.columns:
            logger.warning("TGACharacterizer: 'mass_mg' column not found; cannot compute 'mass_pct'.")
            return df

        df = df.copy()
        min_mass = df["mass_mg"].min()
        max_mass = df["mass_mg"].max()
        if max_mass == min_mass:
            logger.warning("TGACharacterizer: 'mass_mg' has no range; 'mass_pct' set to 0.")
            df["mass_pct"] = 0.0
        else:
            df["mass_pct"] = (df["mass_mg"] - min_mass) / (max_mass - min_mass) * 100

        return df
