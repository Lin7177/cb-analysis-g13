"""Offline adapter for the team's local market-data store (nautilus-style parquet catalog).

The store path stays outside the repository; point MARKET_CATALOG_DIR at it (env var or
argument). Factor panels are tidy (tr_code, date_time, factor_value) daily snapshots keyed
by convertible-bond code like 113659.SH / 123183.SZ; Qty_* panels carry underlying-stock
fundamentals mapped onto the same bond codes.
"""
import os
from pathlib import Path
import pandas as pd

DEFAULT_CATALOG_DIR = os.environ.get('MARKET_CATALOG_DIR', '')

FACTOR_FILES = {
    'price': 'Fund_ClosePrice',
    'premium': 'Fund_ConvertPremiumRate',
    'guaranteed_price': 'Fund_GuaranteedPrice',
    'beta': 'Tech_HisBETA',
    'cb_corr': 'Tech_HisRelation',
    'amount': 'Fund_AmountD',
    'turnover20': 'Turn_TurnoverD20',
    'remaining_scale': 'Fund_remaining_scale',
    'force_redeem_phase': 'Fund_ForceRedeem_phase',
    'downrev_count': 'Fund_downRevision_count_hist',
    'equity_to_assets': 'Qty_EquitytoAssets',
    'current_ratio': 'Qty_CurrentRatio',
    'roe': 'Qty_ROE',
    'profit_growth': 'Qty_NetProfitsGrowth',
    'revenue_growth': 'Qty_TotalRevenueGrowth',
}

def catalog_dir(catalog_root: str | None = None) -> Path:
    path = Path(catalog_root or DEFAULT_CATALOG_DIR)
    if not path.exists():
        raise FileNotFoundError(
            f'market catalog not found at {path}; set MARKET_CATALOG_DIR or pass catalog_dir')
    return path

def load_factor_raw(name: str, catalog_root: str | None = None) -> pd.DataFrame:
    """Return tidy panel: bond_code, date (Timestamp midnight), value."""
    path = catalog_dir(catalog_root) / 'factor' / f'{FACTOR_FILES.get(name, name)}.parquet'
    df = pd.read_parquet(path)
    df = df.rename(columns={'tr_code': 'bond_code', 'factor_value': 'value'})
    df['date'] = pd.to_datetime(df['date_time']).dt.normalize()
    return df[['bond_code', 'date', 'value']]

def load_factor_wide(name: str, catalog_root: str | None = None) -> pd.DataFrame:
    """Return wide panel indexed by date, one column per bond code."""
    tidy = load_factor_raw(name, catalog_root)
    wide = tidy.pivot_table(index='date', columns='bond_code', values='value', aggfunc='last')
    return wide.sort_index()

def export_factors(names: list[str], out_dir: Path, catalog_root: str | None = None) -> dict:
    """Export requested factors as gzipped wide CSVs; return metadata for the manifest."""
    out_dir.mkdir(parents=True, exist_ok=True)
    meta = {}
    for name in names:
        wide = load_factor_wide(name, catalog_root)
        target = out_dir / f'mkt_{name}.csv.gz'
        wide.to_csv(target, compression='gzip')
        meta[name] = {'file': target.name, 'rows': int(wide.shape[0]),
                      'bonds': int(wide.shape[1]),
                      'first': wide.index.min().date().isoformat(),
                      'last': wide.index.max().date().isoformat()}
    return meta
