"""Fama-MacBeth and RankIC weight estimation on the market-wide CB panel.

Per month-end t (last session of the month): cross-sectionally winsorize + z-score the
features, keep bonds in the tradable universe, then regress the forward ~120-session
return on the features. Estimation excludes our 18 research bonds (out-of-sample use).

Weights: w_FM  = normalized |mean FM slope| (association strength, not direction)
         w_IC  = normalized max(ICIR, 0)
         final = mean of the two, mapped to the six dimensions and renormalized.
"""
import numpy as np
import pandas as pd
from scipy import stats

FEATURE_TO_DIM = {'rating_ord': 'D1', 'solv': 'D1', 'low_prem': 'D2',
                  'debt_cov': 'D3', 'link': 'D4', 'dd20': 'D5', 'turn': 'D5',
                  'lossfreq': 'D6', 'resid': 'D2'}
# V6: residual is diagnostic only. Linkage participates in estimation and D4.
EXCLUDED_FROM_WEIGHTS = ['resid']
DIMS = ['D1', 'D2', 'D3', 'D4', 'D5', 'D6']

def month_end_sessions(price_index: pd.DatetimeIndex, first: str, last_before_forward: str) -> list[pd.Timestamp]:
    sessions = pd.Series(price_index, index=price_index)
    monthly = sessions.groupby(sessions.index.to_period('M')).last()
    return [t for t in monthly if pd.Timestamp(first) <= t <= pd.Timestamp(last_before_forward)]

def cross_section(frame: pd.DataFrame, t: pd.Timestamp, exclude_codes: set[str],
                  min_scale: pd.Series | None = None, scale_floor: float = 2.0,
                  price_range: tuple[float, float] = (85.0, 260.0),
                  price_row: pd.Series | None = None) -> pd.Series:
    if t not in frame.index:
        return pd.Series(dtype=float)
    col = frame.loc[t].dropna()
    if price_row is not None:
        ok_price = price_row.reindex(col.index)
        col = col[(ok_price >= price_range[0]) & (ok_price <= price_range[1])]
    if min_scale is not None:
        sc = min_scale.reindex(col.index)
        col = col[sc >= scale_floor]
    col = col.drop([c for c in col.index if c in exclude_codes], errors='ignore')
    if len(col) < 30:
        return pd.Series(dtype=float)
    lo, hi = col.quantile([0.025, 0.975])
    return col.clip(lo, hi)

def zscore(s: pd.Series) -> pd.Series:
    sd = s.std()
    return (s - s.mean()) / sd if sd and np.isfinite(sd) and sd > 0 else s * np.nan

def fama_macbeth(features: dict[str, pd.DataFrame], labels: pd.Series,
                 universe: dict[pd.Timestamp, list[str]]) -> pd.DataFrame:
    """Monthly cross-sectional OLS; returns per-feature slope series.

    Diagnostic-only features (EXCLUDED_FROM_WEIGHTS) are estimated separately so they do
    not distort the slopes of the weighting features through collinearity.
    """
    est_features = {f: features[f] for f in features if f not in EXCLUDED_FROM_WEIGHTS}
    diag_features = {f: features[f] for f in features if f in EXCLUDED_FROM_WEIGHTS}
    slopes = {f: {} for f in features}
    for t, label in labels.items():
        cols = universe.get(t) or []
        if len(cols) < 30:
            continue
        X = pd.DataFrame({f: est_features[f].loc[t, cols] for f in est_features}, index=cols)
        X = X.apply(zscore)
        y = zscore(label.reindex(cols))
        mask = X.notna().all(axis=1) & y.notna()
        if mask.sum() < 30:
            continue
        Xa = np.column_stack([np.ones(mask.sum()), X[mask].values])
        beta_vec, *_ = np.linalg.lstsq(Xa, y[mask].values, rcond=None)
        for k, f in enumerate(est_features):
            slopes[f][t] = beta_vec[1 + k]
        for f, frame in diag_features.items():
            sub = frame.loc[t, cols]
            ok = sub.notna() & y.notna()
            slopes[f][t] = stats.spearmanr(sub[ok], y[ok]).statistic if ok.sum() >= 30 else np.nan
    return pd.DataFrame(slopes).sort_index()

def newey_west_t(series: pd.Series, lags: int = 6) -> float:
    s = series.dropna()
    n = len(s)
    if n < 5:
        return np.nan
    x = s.values - s.mean()
    gamma0 = np.mean(x * x)
    nw = gamma0
    for l in range(1, min(lags, n - 1) + 1):
        w = 1 - l / (lags + 1)
        nw += 2 * w * np.mean(x[l:] * x[:-l])
    se = np.sqrt(nw / n)
    return s.mean() / se if se > 0 else np.nan

def rank_ic_series(features: dict[str, pd.DataFrame], labels: pd.Series,
                   universe: dict[pd.Timestamp, list[str]]) -> pd.DataFrame:
    ics = {f: {} for f in features}
    for t, label in labels.items():
        cols = universe.get(t) or []
        if len(cols) < 30:
            continue
        y = label.reindex(cols)
        for f in features:
            x = features[f].loc[t, cols]
            ok = x.notna() & y.notna()
            if ok.sum() >= 30:
                rho = stats.spearmanr(x[ok], y[ok]).statistic
                ics[f][t] = rho
    return pd.DataFrame(ics).sort_index()

def normalize_positive(v: pd.Series) -> pd.Series:
    v = v.clip(lower=0.0)
    total = v.sum()
    return v / total if total > 0 else v * np.nan

def dimension_weights(fm_slopes: pd.DataFrame, ic_series: pd.DataFrame) -> dict:
    keep = [f for f in fm_slopes.columns if f not in EXCLUDED_FROM_WEIGHTS]
    fm_mean = fm_slopes[keep].mean()
    fm_weighted = normalize_positive(fm_mean.abs())
    ic_mean = ic_series[keep].mean()
    ic_ir = (ic_series[keep].mean() / ic_series[keep].std()).replace([np.inf, -np.inf], np.nan).fillna(0)
    ic_weighted = normalize_positive(ic_ir.clip(lower=0))
    feature_final = ((fm_weighted + ic_weighted) / 2).fillna(0)
    dims = {}
    for d in DIMS:
        dims[d] = float(sum(w for f, w in feature_final.items() if FEATURE_TO_DIM[f] == d))
    total = sum(dims.values())
    dims = {d: w / total for d, w in dims.items()}
    return {'feature_fm': fm_weighted.to_dict(), 'feature_ic': ic_weighted.to_dict(),
            'feature_final': feature_final.to_dict(), 'dimension': dims}
