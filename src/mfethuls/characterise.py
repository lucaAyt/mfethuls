import pandas as pd

from mfethuls.instruments import instrumentation as instrm


def characterise(instrmnt_kw, df: pd.DataFrame, *args, **kwargs):
    instrmnt_kw_lwr = instrmnt_kw.lower()
    obj = None

    if instrmnt_kw_lwr == 'dsc':
        if not obj:
            obj = instrm.DSC()
            obj.df = df

            obj.characterise_data(*args, **kwargs)
    else:
        raise NameError(f'No characterise functionality for: {instrmnt_kw}')
