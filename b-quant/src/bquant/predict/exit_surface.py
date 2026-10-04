"""Exit-value surfaces: reprice the convertible at the horizon over a spot grid and spread scenarios."""
from datetime import date
import numpy as np
from ..pricing.model import dated_cashflows, tree_value

GRID_LO, GRID_HI = 0.3, 3.0

def build_surface(term, spot_T, sigma, riskfree, spreads, evaluation, grid_n=91, steps=401):
    """Return {spread: (spots, values)} — model exit value per 100 face at `evaluation`."""
    spots = np.geomspace(GRID_LO * spot_T, GRID_HI * spot_T, grid_n)
    out = {}
    for s in spreads:
        vals = np.array([tree_value(term, float(S), sigma, riskfree, s, steps=steps, evaluation=evaluation) for S in spots])
        out[s] = (spots, vals)
    return out

def price_on_surface(surf, spread, s_H):
    """Interpolate the surface at terminal spots; linear in log-spot, clamped to grid."""
    spots, vals = surf[spread]
    x = np.log(np.clip(np.asarray(s_H, dtype=float), spots[0], spots[-1]))
    return np.interp(x, np.log(spots), vals)

def coupons_between(term, start: date, horizon: date):
    """Contractual cash paid in (start, horizon]; the final maturity redemption is an exit
    value in every path, so it is never counted here regardless of where horizon falls."""
    maturity = date.fromisoformat(term['maturity_date'])
    return sum(a for d, a in dated_cashflows(term) if start < d <= horizon and d < maturity)

def surface_interp_error(term, spot_T, sigma, riskfree, spread, evaluation, surf, n=8, seed=7, steps=401):
    """Max |interpolated - direct| over interior grid midpoints; honest bound on the interpolation layer."""
    rng = np.random.default_rng(seed)
    spots = surf[spread][0]
    probes = np.exp(rng.uniform(np.log(spots[1]), np.log(spots[-2]), size=n))
    direct = np.array([tree_value(term, float(S), sigma, riskfree, spread, steps=steps, evaluation=evaluation) for S in probes])
    interp = price_on_surface(surf, spread, probes)
    return float(np.max(np.abs(direct - interp))), probes, direct, interp
