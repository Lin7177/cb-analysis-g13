"""Walk-forward calibration: at past roots, predict the 6-month return distribution with
data available up to the root only, then compare against the realized outcome."""
from datetime import date
import zlib
import numpy as np
import pandas as pd
from .exit_surface import build_surface, coupons_between, price_on_surface
from .simulate import bootstrap_log_returns, gbm_log_returns

def stable_seed(*parts) -> int:
    return zlib.crc32('|'.join(str(p) for p in parts).encode())

ROOTS = [date(2021, 9, 30), date(2022, 9, 30), date(2023, 9, 29), date(2024, 9, 30), date(2025, 9, 30), date(2026, 3, 31)]
MIN_RET = 126          # need >= ~6 months of return history before the root
N_PATHS = 10000

def _plus6m(d: date) -> date:
    y, m = d.year, d.month + 6
    if m > 12: y, m = y + 1, m - 12
    try: return d.replace(year=y, month=m)
    except ValueError: return d.replace(year=y, month=m, day=28)

def _last_on_or_before(frame, when: date):
    part = frame[frame.date <= pd.Timestamp(when)]
    return None if part.empty else (part.date.iloc[-1], float(part.close.iloc[-1]))

def run_walkforward(terms, base, daily, idx, curve, riskfree_of, n_paths=N_PATHS, block=21):
    """Return per (bond, root) calibration rows plus skipped-root notes."""
    rows, skipped = [], []
    for b in base.to_dict('records'):
        term = terms[str(b['bond_key'])]
        maturity = date.fromisoformat(term['maturity_date'])
        stock = daily.loc[daily.asset_key == b['stock_key']].sort_values('date')
        bond = daily.loc[(daily.asset_key == b['bond_key']) & (daily.asset_type == 'bond')].sort_values('date')
        valid = stock.date.map(idx) - stock.date.shift().map(idx) == 1
        sret = stock.qfq_close.pct_change(fill_method=None).where(valid).dropna()
        sret.index = stock.date.loc[sret.index].values  # date index for root filtering
        for root in ROOTS:
            horizon = min(_plus6m(root), date(2026, 9, 30))
            if horizon <= root: continue
            ret_le = sret[sret.index <= pd.Timestamp(root)]
            if len(ret_le) < MIN_RET:
                skipped.append(dict(bond_key=b['bond_key'], root=root.isoformat(), reason=f'returns_before_root={len(ret_le)}<{MIN_RET}')); continue
            p0 = _last_on_or_before(bond, root)
            if p0 is None or p0[1] <= 0:
                skipped.append(dict(bond_key=b['bond_key'], root=root.isoformat(), reason='no_bond_quote_at_root')); continue
            root_dt, P0 = p0
            if maturity <= horizon:
                realized_exit = float(term['redemption_amount_including_last_coupon'])
                realized_date = maturity
            else:
                p1 = _last_on_or_before(bond, horizon)
                if p1 is None:
                    skipped.append(dict(bond_key=b['bond_key'], root=root.isoformat(), reason='no_bond_quote_at_horizon')); continue
                realized_date, realized_exit = p1[0], p1[1]
            tail = ret_le.tail(120)
            sigma = float(tail.std(ddof=1) * np.sqrt(252))
            spot0 = _last_on_or_before(stock, root)[1]
            r = riskfree_of(maturity)
            horizon_sessions = int(np.ceil((horizon - root).days / 365 * 252))
            coupons = coupons_between(term, root_dt.date(), horizon)
            realized = (realized_exit + coupons_between(term, root_dt.date(), realized_date.date())) / P0 * 100 - 100
            surf = build_surface(term, spot0, sigma, r, [.02], evaluation=horizon, grid_n=61)
            try:
                tot = bootstrap_log_returns(ret_le.to_numpy(), n_paths, horizon_sessions, block=block, seed=stable_seed(b['bond_key'], root.isoformat()))
                method = 'bootstrap'
            except ValueError:
                tot = gbm_log_returns(sigma, (horizon - root).days / 365, n_paths, seed=stable_seed(b['bond_key'], root.isoformat()))
                method = 'gbm_fallback'
            exits = price_on_surface(surf, .02, spot0 * np.exp(tot))
            pred = (exits + coupons) / P0 * 100 - 100
            q = np.percentile(pred, [5, 50, 95])
            rows.append(dict(bond_key=b['bond_key'], bond_name=b['bond_name'], root=root.isoformat(), horizon=horizon.isoformat(),
                             method=method, n_paths=n_paths, sigma_used=sigma, coupons_before_tax=coupons, price_root=P0,
                             realized_exit=realized_exit, realized_return_pct=realized, pred_p05=q[0], pred_p50=q[1], pred_p95=q[2],
                             covered=bool(q[0] <= realized <= q[2]), pit=float(np.mean(pred <= realized)) * 100,
                             realized_date=str(realized_date.date())))
    return rows, skipped
