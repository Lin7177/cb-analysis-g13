"""B4 market-performance prediction: six-month return distributions for the 18 bonds.

Primary engine: historical block bootstrap of each stock's real daily returns, repriced at
the horizon on a CRR-tree exit surface (the B1 pricing core). Secondary: zero-drift GBM.
Two exit bases bracket the premium question: model convergence vs. persistence of the
T-day model-vs-market gap. Outputs are model estimates validated walk-forward — not
promises, and the no-call/no-reset clause scope of the tree is inherited as-is.
"""
from datetime import date
import argparse, hashlib, json, platform, sys
from pathlib import Path
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from bquant.terms import load_base, load_curve, load_daily, load_terms, session_index, term_map
from bquant.pricing.model import tree_value
from bquant.predict.exit_surface import build_surface, coupons_between, price_on_surface, surface_interp_error
from bquant.predict.simulate import bootstrap_log_returns, gbm_log_returns, summarize
from bquant.predict.walkforward import ROOTS, run_walkforward, stable_seed

T = date(2026, 9, 30); H = date(2027, 3, 30)
SPREADS = [.005, .02, .05]; BASE_SPREAD = .02; STRESS_SPREAD = .05
N_PATHS = 10000; BLOCK = 21; GRID_N = 91; STEPS = 401
CALL_THRESHOLD = 130.0

def stock_returns(daily, stock_key, idx):
    stock = daily.loc[daily.asset_key == stock_key].sort_values('date')
    return stock.qfq_close.pct_change(fill_method=None).where(stock.date.map(idx) - stock.date.shift().map(idx) == 1).dropna()

def horizon_session_count(idx):
    lo, hi = pd.Timestamp(2026, 3, 31), pd.Timestamp(2026, 9, 30)
    return sum(1 for d, i in idx.items() if lo < d <= hi)

def exit_rows(b, term, ret, sigma, r, surf, model_T, horizon, horizon_sessions, coupons):
    P0 = float(b['bond_close']); spot0 = float(b['stock_close'])
    gap_ratio = P0 / model_T if model_T > 0 else 1.0
    tau = (horizon - T).days / 365
    rows = []
    engines = []
    try:
        boot = bootstrap_log_returns(ret.to_numpy(), N_PATHS, horizon_sessions, block=BLOCK, seed=stable_seed(b['bond_key'], 'boot'))
        engines.append(('bootstrap', boot))
    except ValueError:
        pass  # short history (61-bar Xiang 26): GBM only
    engines.append(('gbm', gbm_log_returns(sigma, tau, N_PATHS, seed=stable_seed(b['bond_key'], 'gbm'))))
    for method, tot in engines:
        s_H = spot0 * np.exp(tot)
        for spread in ([BASE_SPREAD, STRESS_SPREAD] if method == 'bootstrap' else [BASE_SPREAD]):
            base_exit = price_on_surface(surf, spread, s_H)
            for basis, exit_vals in [('convergence', base_exit), ('gap_persist', base_exit * gap_ratio)]:
                pct = (exit_vals + coupons) / P0 * 100 - 100
                st = summarize(pct, exit_vals, CALL_THRESHOLD)
                eq = np.percentile(exit_vals, [5, 25, 50, 75, 95])
                rows.append(dict(bond_key=b['bond_key'], bond_name=b['bond_name'], method=method, exit_basis=basis,
                                 spread_bp=int(spread * 10000), n_paths=N_PATHS, horizon_date=horizon.isoformat(),
                                 horizon_sessions=horizon_sessions, coupons_before_tax=coupons, price_T=P0,
                                 exit_p05=eq[0], exit_p25=eq[1], exit_p50=eq[2], exit_p75=eq[3], exit_p95=eq[4], **st,
                                 status='dual_basis_full' if method == 'bootstrap' else 'gbm_only_short_history'))
    return rows

def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--skip-walkforward', action='store_true')
    a = ap.parse_args()
    here = Path(__file__).resolve().parents[3] / 'results' / 'predict'
    here.mkdir(parents=True, exist_ok=True)
    terms_raw, base, curve, daily = load_terms(), load_base(), load_curve(), load_daily()
    terms = term_map(terms_raw); idx = session_index(daily)
    hs = horizon_session_count(idx)
    rows, checks = [], []
    for b in base.to_dict('records'):
        term = terms[str(b['bond_key'])]
        maturity = date.fromisoformat(term['maturity_date'])
        years = (maturity - T).days / 365
        r = float(np.log1p(np.interp(years, curve.tenor_years, curve.yield_pct) / 100))
        ret = stock_returns(daily, b['stock_key'], idx)
        sigma = float(ret.tail(120).std(ddof=1) * np.sqrt(252))
        P0 = float(b['bond_close'])
        if maturity <= H:  # Lege: redemption is the exit; no distribution to simulate
            pay = float(term['redemption_amount_including_last_coupon'])
            rows.append(dict(bond_key=b['bond_key'], bond_name=b['bond_name'], method='maturity_payoff', exit_basis='deterministic',
                             spread_bp=0, n_paths=0, horizon_date=maturity.isoformat(), horizon_sessions=hs, coupons_before_tax=0.0,
                             price_T=P0, exit_p05=pay, exit_p25=pay, exit_p50=pay, exit_p75=pay, exit_p95=pay,
                             p05=(pay / P0 - 1) * 100, p25=(pay / P0 - 1) * 100, p50=(pay / P0 - 1) * 100, p75=(pay / P0 - 1) * 100,
                             p95=(pay / P0 - 1) * 100, mean=(pay / P0 - 1) * 100, std=0.0, p_loss=float(pay < P0) * 100,
                             p_gt5=float(pay / P0 > 1.05) * 100, p_exit_gt130=float(pay > CALL_THRESHOLD) * 100,
                             status='maturity_payoff_deterministic'))
            continue
        horizon = min(H, maturity)
        surf = build_surface(term, float(b['stock_close']), sigma, r, SPREADS, evaluation=horizon, grid_n=GRID_N, steps=STEPS)
        model_T = tree_value(term, float(b['stock_close']), sigma, r, BASE_SPREAD, steps=STEPS, evaluation=T)
        coupons = coupons_between(term, T, horizon)
        rows += exit_rows(b, term, ret, sigma, r, surf, model_T, horizon, hs, coupons)
        err, probes, direct, interp = surface_interp_error(term, float(b['stock_close']), sigma, r, BASE_SPREAD, horizon, surf, n=8, steps=STEPS)
        checks.append(dict(bond_key=b['bond_key'], bond_name=b['bond_name'], max_abs_interp_error=err,
                           probe_spots=';'.join(f'{p:.2f}' for p in probes), direct=';'.join(f'{d:.3f}' for d in direct),
                           interp=';'.join(f'{i:.3f}' for i in interp)))
    pd.DataFrame(rows).to_csv(here / 'predictions.csv', index=False, encoding='utf-8-sig')
    pd.DataFrame(checks).to_csv(here / 'surface_check.csv', index=False, encoding='utf-8-sig')
    calib, skipped = ([], [])
    if not a.skip_walkforward:
        wf_r = lambda mat: float(np.log1p(np.interp(((mat - T).days / 365), curve.tenor_years, curve.yield_pct) / 100))
        calib, skipped = run_walkforward(terms, base, daily, idx, curve, wf_r, n_paths=6000, block=BLOCK)
        pd.DataFrame(calib).to_csv(here / 'calibration.csv', index=False, encoding='utf-8-sig')
        pd.DataFrame(skipped).to_csv(here / 'calibration_skipped.csv', index=False, encoding='utf-8-sig')
    import QuantLib as ql
    data_dir = Path(__file__).resolve().parents[3] / 'data' / 'curated'
    manifest = dict(module='B4 market-performance prediction', T=T.isoformat(), horizon=H.isoformat(),
                    horizon_sessions=hs, spreads_bp=[int(s * 10000) for s in SPREADS], base_spread_bp=200, stress_spread_bp=500,
                    n_paths=N_PATHS, bootstrap_block_sessions=BLOCK, grid=dict(lo=0.3, hi=3.0, n=GRID_N), tree_steps=STEPS,
                    call_threshold=CALL_THRESHOLD, exit_bases=dict(convergence='exit = tree model value at horizon',
                    gap_persist='exit = model value x T-day market/model ratio (premium gap kept)'),
                    engines=dict(bootstrap='block bootstrap of real daily qfq returns, blocks internally ordered',
                                 gbm='zero-drift lognormal; drift declared not estimated'),
                    walkforward=dict(roots=[d.isoformat() for d in ROOTS], rule='only data up to each root'),
                    special_cases={'SH:123072': 'matures 2026-10-20 before horizon; deterministic redemption exit; last trading 2026-10-15',
                                   'SH:113703': '61 quotes only; GBM engine only, no bootstrap'},
                    limitations=['Fixed conversion price; no rolling call / discretionary reset / put; inherited from the B1 pricing core',
                                'Credit spreads are analyst scenarios, not rating-calibrated market quotes',
                                'Bootstrap resamples overlapping history; effective sample size is smaller than the path count',
                                'Walk-forward applies T-day terms and the T-day Treasury curve backward; historical conversion prices are unavailable',
                                'Exit values are model references, not executable prices; returns are before tax and fees',
                                'p_exit_gt130 flags the call-price region only; actual redemption depends on issuer decisions'],
                    runtime=dict(python=platform.python_version(), QuantLib=ql.__version__, numpy=np.__version__, pandas=pd.__version__),
                    input_sha256={p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(data_dir.glob('*')) if p.is_file()})
    (here / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    df = pd.DataFrame(rows)
    print(df[['bond_name', 'method', 'exit_basis', 'spread_bp', 'p05', 'p50', 'p95', 'p_loss']].round(2).to_string(index=False))
    print(f'\nrows={len(df)} horizon_sessions={hs}')
    if calib:
        c = pd.DataFrame(calib)
        print(f'walk-forward: n={len(c)} coverage(p5-p95)={c.covered.mean() * 100:.1f}% mean|PIT-50|={float((c.pit - 50).abs().mean()):.1f}pp')

if __name__ == '__main__':
    main()
