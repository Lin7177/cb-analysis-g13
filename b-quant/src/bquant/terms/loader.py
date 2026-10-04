"""Shared loaders for verified terms, market base rows, curve and daily panels."""
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]  # b-quant/
DATA = ROOT / 'data' / 'curated'

def load_terms() -> pd.DataFrame:
    return pd.read_csv(DATA / 'terms_verified.csv').fillna('')

def load_base() -> pd.DataFrame:
    return pd.read_csv(DATA / 'base.csv')

def load_curve() -> pd.DataFrame:
    return pd.read_csv(DATA / 'riskfree_curve_20260929.csv')

def load_daily() -> pd.DataFrame:
    daily = pd.read_csv(DATA / 'b_daily_group13_20200101_20260930.csv.gz')
    daily['date'] = pd.to_datetime(daily.date)
    return daily

def term_map(terms: pd.DataFrame) -> dict:
    return {str(r['bond_key']): r for _, r in terms.iterrows()}

def session_index(daily: pd.DataFrame) -> dict:
    """Global market-session order from the stock panel (both exchanges share sessions)."""
    dates = sorted(daily.loc[daily.asset_type == 'stock', 'date'].unique())
    return {d: i for i, d in enumerate(dates)}
