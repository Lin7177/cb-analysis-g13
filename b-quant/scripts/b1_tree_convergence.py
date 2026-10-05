"""CRR tree step-count convergence check: 401 vs 801 steps, auditing main-deck p26.

The main deck p26 claims "401 步 vs 801 步，全池定价差异 <0.163%" (previously
recorded only in the legacy workbench docs, see
docs/methodology/数字勘误与依据边界.md item B4; the b-quant README rounds the same
number to "401步收敛<0.17%"). This script recomputes, for all 18 pool bonds, the
QuantLib CRR convertible-tree reference value at 401 and 801 steps with the exact
conventions of scripts/b1_price_bonds.py (the script that restored
data/inputs/b2_pricing_recovered.csv, mirroring bquant/predict/run.py, STEPS=401):
  r     = log1p(curve yield interpolated at the bond's remaining maturity
          (maturity_date - T).days/365), continuous compounding;
  sigma = last-120-session (session-contiguous) stock qfq overnight return std
          x sqrt(252);
  spot  = stock_close on the 2026-09-30 observation day (base.csv); bond terms from
          terms_verified.csv; spread = 200bp; fixed conversion price, no call / no
          reset / no put (the declared clause scope of the B1 pricing core);
  evaluation date T = 2026-09-30.
Per bond rel_diff_pct = |v801 - v401| / v401 x 100; the deck number refers to the
pool MAXIMUM ("全池定价差异"). Recomputed r / sigma / v401 are cross-checked against
the riskfree_cont / sigma / tree_value columns of b2_pricing_recovered.csv (the
stored columns are rounded, so agreement is asserted at those tolerances).

Writes results/pricing/tree_convergence.csv (bond_key, bond_name, v401, v801,
rel_diff_pct; new file, no existing file is touched) and prints the pool max/mean
against the 0.163% claim. Model reference values only, not tradable prices.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]          # b-quant/
sys.path.insert(0, str(ROOT / 'src'))
from bquant.terms import load_base, load_curve, load_daily, load_terms, session_index, term_map
from bquant.pricing.model import tree_value

T = date(2026, 9, 30)
BASE_SPREAD = 0.02                       # 200bp debt-floor scenario (same as B1 core)
STEPS_LO, STEPS_HI = 401, 801
DECK_MAX_PCT = 0.163                     # main deck p26 "全池定价差异 <0.163%"
RECOVERED = ROOT / 'data' / 'inputs' / 'b2_pricing_recovered.csv'
OUT = ROOT / 'results' / 'pricing' / 'tree_convergence.csv'


def stock_returns(daily: pd.DataFrame, stock_key: str, idx: dict) -> pd.Series:
    """Overnight qfq returns kept only across consecutive market sessions (same as predict.run)."""
    stock = daily.loc[daily.asset_key == stock_key].sort_values('date')
    return (stock.qfq_close.pct_change(fill_method=None)
            .where(stock.date.map(idx) - stock.date.shift().map(idx) == 1).dropna())


def main() -> None:
    terms_raw, base, curve, daily = load_terms(), load_base(), load_curve(), load_daily()
    terms = term_map(terms_raw)
    idx = session_index(daily)
    recovered = pd.read_csv(RECOVERED).set_index('bond_key')

    rows = []
    for b in base.to_dict('records'):
        term = terms[str(b['bond_key'])]
        maturity = date.fromisoformat(term['maturity_date'])
        years = (maturity - T).days / 365
        r = float(np.log1p(np.interp(years, curve.tenor_years, curve.yield_pct) / 100))
        ret = stock_returns(daily, b['stock_key'], idx)
        sigma = float(ret.tail(120).std(ddof=1) * np.sqrt(252))
        spot = float(b['stock_close'])
        v401 = tree_value(term, spot, sigma, r, BASE_SPREAD, steps=STEPS_LO, evaluation=T)
        v801 = tree_value(term, spot, sigma, r, BASE_SPREAD, steps=STEPS_HI, evaluation=T)
        ref = recovered.loc[b['bond_key']]
        rows.append(dict(
            bond_key=b['bond_key'], bond_name=b['bond_name'],
            v401=round(v401, 4), v801=round(v801, 4),
            rel_diff_pct=round(abs(v801 - v401) / v401 * 100, 4),
            # cross-checks against the recovered B2 inputs (stored rounded)
            r_vs_recovered=float(f'{abs(r - ref.riskfree_cont):.2e}'),
            sigma_vs_recovered=float(f'{abs(sigma - ref.sigma):.2e}'),
            v401_vs_recovered=round(abs(v401 - ref.tree_value), 4)))

    out = pd.DataFrame(rows)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT, index=False, encoding='utf-8-sig')
    print(out[['bond_key', 'bond_name', 'v401', 'v801', 'rel_diff_pct',
               'r_vs_recovered', 'sigma_vs_recovered', 'v401_vs_recovered']].to_string(index=False))
    print(f"\nwrote {OUT} ({len(out)} bonds; T={T.isoformat()}, spread={int(BASE_SPREAD * 10000)}bp, "
          f"steps {STEPS_LO} vs {STEPS_HI})")
    print(f"cross-check vs {RECOVERED.name}: max|r diff| = {out.r_vs_recovered.max():.1e}, "
          f"max|sigma diff| = {out.sigma_vs_recovered.max():.1e}, "
          f"max|v401 - tree_value| = {out.v401_vs_recovered.max():.4f}")
    rel_max, rel_mean = out.rel_diff_pct.max(), out.rel_diff_pct.mean()
    print(f"convergence: max rel_diff = {rel_max:.4f}%  |  mean rel_diff = {rel_mean:.4f}%  "
          f"| deck p26 claims <{DECK_MAX_PCT}%  ->  {'HIT' if rel_max < DECK_MAX_PCT else 'MISS'}")


if __name__ == '__main__':
    main()
