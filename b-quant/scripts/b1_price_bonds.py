"""B1 bond pricing: restore the lost B2 inputs (debt floor 200bp + CRR tree reference).

Rebuilds, from in-repo inputs only, the per-bond pricing results the compose scoring
chain expects as its B2 input (historically work/B_methods/B2/results.csv):
  - debt_floor_200bp: contractual cash flows (coupons + redemption incl. last coupon)
    discounted at the riskfree rate + 200bp credit-spread scenario (continuous compounding);
  - tree_value: CRR binomial reference value per 100 face (401 steps, fixed conversion
    price, no call/no reset/no put - the declared clause scope of the B1 pricing core);
  - tree_gap_pct = (tree_value / bond_close - 1) * 100 (positive = model sees the bond
    as cheap vs. market);
  - maturity_date from terms_verified.csv.

Conventions mirror the B1 pricing core as used by bquant/predict/run.py:
  r     = log1p(curve yield interpolated at the bond's remaining maturity)  [continuous]
  sigma = stock last-120-session (session-contiguous) qfq return std * sqrt(252)
  spot  = stock_close on the 2026-09-30 observation day; bond_close = base.csv close
  spread= 200bp; steps = 401; evaluation date T = 2026-09-30.

Writes data/inputs/b2_pricing_recovered.csv (new file; no existing file is touched).
Outputs are model references for scoring, not tradable prices or recommendations.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from bquant.terms import load_base, load_curve, load_daily, load_terms, session_index, term_map
from bquant.pricing.model import debt_floor, tree_value

T = date(2026, 9, 30)
BASE_SPREAD = 0.02  # 200bp debt-floor scenario
STEPS = 401
OUT = Path(__file__).resolve().parents[1] / 'data' / 'inputs' / 'b2_pricing_recovered.csv'


def stock_returns(daily: pd.DataFrame, stock_key: str, idx: dict) -> pd.Series:
    """Overnight qfq returns kept only across consecutive market sessions (same as predict.run)."""
    stock = daily.loc[daily.asset_key == stock_key].sort_values('date')
    return (stock.qfq_close.pct_change(fill_method=None)
            .where(stock.date.map(idx) - stock.date.shift().map(idx) == 1).dropna())


def main() -> None:
    terms_raw, base, curve, daily = load_terms(), load_base(), load_curve(), load_daily()
    terms = term_map(terms_raw)
    idx = session_index(daily)
    rows = []
    for b in base.to_dict('records'):
        term = terms[str(b['bond_key'])]
        maturity = date.fromisoformat(term['maturity_date'])
        years = (maturity - T).days / 365
        r = float(np.log1p(np.interp(years, curve.tenor_years, curve.yield_pct) / 100))
        ret = stock_returns(daily, b['stock_key'], idx)
        sigma = float(ret.tail(120).std(ddof=1) * np.sqrt(252))
        bond_close = float(b['bond_close'])
        floor = debt_floor(term, T, r, BASE_SPREAD)
        tv = tree_value(term, float(b['stock_close']), sigma, r, BASE_SPREAD, steps=STEPS, evaluation=T)
        gap = (tv / bond_close - 1) * 100
        rows.append(dict(bond_key=b['bond_key'],
                         debt_floor_200bp=round(floor, 3), tree_gap_pct=round(gap, 2),
                         tree_value=round(tv, 3), bond_close=bond_close,
                         maturity_date=term['maturity_date'], bond_name=b['bond_name'],
                         coverage=round(floor / bond_close, 3),
                         riskfree_cont=round(r, 6), sigma=round(sigma, 4), tree_steps=STEPS))
    out = pd.DataFrame(rows)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT, index=False, encoding='utf-8-sig')
    print(out[['bond_key', 'bond_name', 'debt_floor_200bp', 'coverage', 'tree_gap_pct',
               'tree_value', 'bond_close', 'maturity_date']].to_string(index=False))
    print(f'\nwrote {OUT} ({len(out)} bonds; T={T.isoformat()}, spread={int(BASE_SPREAD * 10000)}bp, steps={STEPS})')


if __name__ == '__main__':
    main()
