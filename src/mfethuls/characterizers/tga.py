import logging

import pandas as pd

logger = logging.getLogger(__name__)


class TGACharacterizer:
    def characterize(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df

        # A mass_pct from the file (or a definition's derived step) is kept as it is, gaps included.
        if "mass_pct" in df.columns:
            return df

        if "mass_mg" not in df.columns:
            logger.warning("TGACharacterizer: 'mass_mg' column not found; cannot compute 'mass_pct'.")
            return df

        # Mass as % of the initial mass (TGA convention: the curve starts at 100 %), per curve.
        df = df.copy()
        mass = pd.to_numeric(df["mass_mg"], errors="coerce")
        groups = df["name"] if "name" in df.columns else pd.Series(0, index=df.index)
        initial = mass.groupby(groups).transform(lambda m: m.dropna().iloc[0] if m.notna().any() else float("nan"))
        if (initial == 0).any():
            logger.warning("TGACharacterizer: an initial mass of 0; its 'mass_pct' is left empty.")
        df["mass_pct"] = mass / initial.where(initial != 0) * 100

        return df
