"""Historical proxies used by the V6 market-wide weight estimator.

D1: rating_ord (current rating snapshot), solv (equity/assets).
D2: low_prem (negative premium); resid is diagnostic only.
D3: debt_cov (guaranteed price/market price).
D4: link (beta times correlation, distinct from the scoring beta times R squared).
D5: dd20 (20-session drawdown), turn (log turnover).
D6: lossfreq (negative historical frequency of 120-session losses below -10%).

These are proxies for presentation dimensions, not the actual 18-bond scores.
Snapshot ratings and the proxy/scoring differences remain declared limitations.
"""
from pathlib import Path
import numpy as np
import pandas as pd

DATA = Path(__file__).resolve().parents[3] / 'data' / 'curated' / 'market'

RATING_ORD = {'AAA': 10, 'AA+': 9, 'AA': 8, 'AA-': 7, 'A+': 6, 'A': 5, 'A-': 4, 'BBB+': 3, 'BBB': 2.5}

def _wide(name: str) -> pd.DataFrame:
    df = pd.read_csv(DATA / f'mkt_{name}.csv.gz', index_col=0, parse_dates=[0])
    return df.apply(pd.to_numeric, errors='coerce')

def _asof(wide: pd.DataFrame, t: pd.Timestamp) -> pd.Series:
    """Last value at or before t for every column."""
    sub = wide.loc[:t]
    if sub.empty:
        return pd.Series(dtype=float)
    return sub.iloc[-1]

def rolling_drawdown(price: pd.DataFrame, window: int = 20) -> pd.DataFrame:
    return price / price.rolling(window, min_periods=max(2, window // 2)).max() - 1.0

def window_loss_frequency(price: pd.DataFrame, horizon: int = 120, stride: int = 5,
                          threshold: float = -0.10, lookback: int = 120) -> pd.DataFrame:
    """Per session: share of trailing sampled windows whose horizon return breached threshold.

    Window ending at session k has return price[k]/price[k-horizon]-1; lossfreq[i] is the
    nan-mean of the breach indicator over k in (i-lookback, i] sampled every `stride`.
    """
    base = price.shift(horizon)
    ret = price / base - 1.0
    indicator = (ret < threshold).astype(float)
    indicator[base.isna() | ret.isna()] = np.nan
    values = indicator.values
    out = np.full(values.shape, np.nan)
    for i in range(lookback, len(price)):
        out[i] = np.nanmean(values[i - lookback + 1:i + 1:stride], axis=0)
    return pd.DataFrame(out, index=price.index, columns=price.columns)

FEATURES = ['rating_ord', 'solv', 'low_prem', 'debt_cov', 'link', 'dd20', 'turn', 'lossfreq', 'resid']

def decomposition_residual(price_t: pd.Series, premium_t: pd.Series, guaranteed_t: pd.Series) -> pd.Series:
    """Cheapness vs the floor+parity decomposition at one date (higher = cheaper).

    Regress price on [1, guaranteed_price, parity] cross-sectionally (parity =
    price/(1+premium)); return the standardized negative residual, i.e. how far the
    bond trades below what its debt floor and parity imply.
    """
    frame = pd.concat([price_t.rename('price'), premium_t.rename('prem'), guaranteed_t.rename('gp')], axis=1).dropna()
    frame = frame[(frame.price > 0) & (frame.prem > -0.9)]
    if len(frame) < 30:
        return pd.Series(dtype=float)
    parity = frame.price / (1.0 + frame.prem)
    X = np.column_stack([np.ones(len(frame)), frame.gp.values, parity.values])
    coef, *_ = np.linalg.lstsq(X, frame.price.values, rcond=None)
    resid = frame.price.values - X @ coef
    resid_std = (resid - resid.mean()) / (resid.std() or 1.0)
    return pd.Series(-resid_std, index=frame.index)

def build_monthly_features(asof_dates: list[pd.Timestamp], ratings: pd.DataFrame | None = None) -> dict[str, pd.DataFrame]:
    """Return {feature_name: DataFrame(index=asof_date, columns=bond_code)}."""
    price = _wide('price')
    premium = _wide('premium')
    guaranteed = _wide('guaranteed_price')
    beta = _wide('beta')
    corr = _wide('cb_corr')
    turnover = _wide('turnover20')
    eta = _wide('equity_to_assets')
    dd20 = rolling_drawdown(price)
    lossf = window_loss_frequency(price)
    rating_ord = pd.Series(dtype=float)
    if ratings is not None and len(ratings):
        rating_ord = ratings.set_index('bond_code')['rating'].map(
            lambda s: RATING_ORD.get(str(s).strip(), np.nan)).dropna()
    rows = {k: {} for k in FEATURES}
    for t in asof_dates:
        p_t = _asof(price, t)
        prem_t = _asof(premium, t)
        gp_t = _asof(guaranteed, t)
        rows['rating_ord'][t] = rating_ord.reindex(p_t.index)
        rows['solv'][t] = _asof(eta, t).reindex(p_t.index)
        rows['low_prem'][t] = -prem_t.reindex(p_t.index)
        rows['debt_cov'][t] = (gp_t / p_t).reindex(p_t.index)
        rows['link'][t] = (_asof(beta, t) * _asof(corr, t)).reindex(p_t.index)
        rows['dd20'][t] = _asof(dd20, t).reindex(p_t.index)
        rows['turn'][t] = np.log(_asof(turnover, t).clip(lower=1e-4)).reindex(p_t.index)
        rows['lossfreq'][t] = -_asof(lossf, t).reindex(p_t.index)
        rows['resid'][t] = decomposition_residual(p_t, prem_t, gp_t).reindex(p_t.index)
    return {k: pd.DataFrame(v).T.sort_index() for k, v in rows.items()}

def forward_return(price: pd.DataFrame, t: pd.Timestamp, horizon: int = 120) -> pd.Series:
    """Return from t to the session ~horizon sessions later (capped at data end)."""
    idx = price.index
    if t not in idx:
        return pd.Series(dtype=float)
    i = idx.get_loc(t)
    j = min(i + horizon, len(idx) - 1)
    if j <= i:
        return pd.Series(dtype=float)
    return (price.iloc[j] / price.iloc[i] - 1.0).replace([np.inf, -np.inf], np.nan)

def constrained_return(price: pd.DataFrame, t: pd.Timestamp, horizon: int = 120,
                       stop: float = -0.15) -> pd.Series:
    """Forward return under a drawdown-stop policy: if the path breaches `stop` before
    horizon, the position is stopped out at `stop`; otherwise the full forward return.

    This matches the report's investor mandate (no leverage, drawdown-averse, 6-month
    window) and is the label the weights should be estimated against.
    """
    idx = price.index
    if t not in idx:
        return pd.Series(dtype=float)
    i = idx.get_loc(t)
    j = min(i + horizon, len(idx) - 1)
    if j <= i:
        return pd.Series(dtype=float)
    window = price.iloc[i:j + 1]
    running_max = window.cummax()
    dd = window / running_max - 1.0
    breach = dd.min() <= stop
    fwd = (window.iloc[-1] / window.iloc[0] - 1.0)
    return fwd.where(~breach, stop)
