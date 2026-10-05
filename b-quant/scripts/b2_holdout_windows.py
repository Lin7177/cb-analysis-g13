"""B2 holdout-improvement and multi-window stability evidence (主PPT p34 / p28).

The main deck cites two linkage numbers that had no in-repo support:
- p34 "传导留出检验 +36.9%": the error reduction of the 120-train / 60-holdout
  OLS versus the "均值猜" (train-mean guess) baseline in the B2 linkage test;
- p28 "窗口 60/120/252 三档并排": beta/R2 of the same paired sample under
  three regression windows, as a stability check.

Method base (reused verbatim, no existing file modified):
- Pairing / estimator: scripts/b2_linkage.py — bond `close` x stock `qfq_close`
  inner-joined by date, daily pct_change, beta = cov(bond, stock)/var(stock),
  R2 = corr(bond, stock)^2 on the LAST n paired returns.
- Holdout (scripts/b2_linkage.beats_holdout): train OLS bond_ret ~ a + b*stock_ret
  on the 120 paired returns immediately preceding the final 60, then
  MSE(mean guess, train mean) and MSE(model) on the final-60 holdout;
  improvement_pct = 100 * (MSE_baseline - MSE_model) / MSE_baseline
  (positive iff test_model_beats_mean is True).

Window rule: a bond yields beta/r2 for window n only with >= n usable returns
(insufficient sample is NaN, e.g. SH:113703 翔26转债 has only 60 paired
returns -> beta_60/r2_60 only). The holdout test needs 120+60 returns, so the
17 judged bonds (18 in base.csv minus 翔26) get improvement_pct and the two
aggregates (mean, median) that are compared against the p34 claim of +36.9%.

Outputs results/linkage/window_stability.csv
(bond_key, beta_60, r2_60, beta_120, r2_120, beta_252, r2_252) and
results/linkage/holdout_improvement.csv
(bond_key, mse_baseline, mse_model, improvement_pct). Both are new files in a
new directory; data/inputs/b3_linkage_recovered.csv and scripts/b2_linkage.py
are not touched by this script.

Run: python scripts/b2_holdout_windows.py   (from b-quant/)
Metrics describe historical prices; they are not recommendations.
"""
from __future__ import annotations

import gzip
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]          # b-quant/
DAILY = ROOT / "data" / "curated" / "b_daily_group13_20200101_20260930.csv.gz"
BASE = ROOT / "data" / "curated" / "base.csv"
OUTDIR = ROOT / "results" / "linkage"

WINDOWS = (60, 120, 252)    # 主PPT p28: 三档窗口并排
TRAIN_N, HOLD_N = 120, 60   # holdout-test design, same as b2_linkage.py
PPT_CLAIM_PCT = 36.9        # 主PPT p34 "传导留出检验 +36.9%"


def load_daily() -> pd.DataFrame:
    with gzip.open(DAILY, "rt", encoding="utf-8") as f:
        daily = pd.read_csv(f, dtype={"asset_key": str, "bond_key": str})
    daily["date"] = pd.to_datetime(daily["date"])
    for field in ("close", "qfq_close"):
        daily[field] = pd.to_numeric(daily[field], errors="coerce")
    return daily


def pair_returns(daily: pd.DataFrame, bond_key: str, stock_key: str) -> pd.DataFrame:
    """Full-history paired daily returns, identical to b2_linkage.pair_returns."""
    bond = daily[daily.asset_key == bond_key].sort_values("date")
    stock = daily[daily.asset_key == stock_key].sort_values("date")
    paired = bond[["date", "close"]].merge(
        stock[["date", "qfq_close"]], on="date", how="inner")
    returns = paired[["close", "qfq_close"]].pct_change().dropna()
    return returns


def beta_r2(returns: pd.DataFrame, window: int) -> tuple[float, float]:
    """beta/R2 on the last `window` paired returns; NaN if fewer are usable."""
    tail = returns.tail(window)
    beta = r2 = float("nan")
    if len(tail) >= window and tail.qfq_close.var() > 0:
        beta = tail.close.cov(tail.qfq_close) / tail.qfq_close.var()
        r = tail.close.corr(tail.qfq_close)
        r2 = r * r
    return float(beta), float(r2)


def holdout_stats(returns: pd.DataFrame) -> dict:
    """120-train OLS vs train-mean guess on the final-60 holdout.

    Returns mse_baseline (mean guess), mse_model, improvement_pct, plus the
    holdout mean MSE for the alternative "holdout-mean baseline" reading of
    均值猜 used only in the口径 diagnostics — nothing else changes.
    """
    out = {"mse_baseline": float("nan"), "mse_model": float("nan"),
           "improvement_pct": float("nan"),
           "mse_baseline_holdout_mean": float("nan")}
    if len(returns) < TRAIN_N + HOLD_N:
        return out
    y = returns.close.values
    x = returns.qfq_close.values
    y_tr, x_tr = y[-(TRAIN_N + HOLD_N):-HOLD_N], x[-(TRAIN_N + HOLD_N):-HOLD_N]
    y_ho, x_ho = y[-HOLD_N:], x[-HOLD_N:]
    if y_tr.var() == 0 or x_tr.var() == 0:
        return out
    coef, *_ = np.linalg.lstsq(np.column_stack([np.ones(TRAIN_N), x_tr]),
                               y_tr, rcond=None)
    pred = coef[0] + coef[1] * x_ho
    mse_model = float(np.mean((y_ho - pred) ** 2))
    mse_base = float(np.mean((y_ho - y_tr.mean()) ** 2))
    out["mse_baseline"] = mse_base
    out["mse_model"] = mse_model
    out["improvement_pct"] = 100.0 * (mse_base - mse_model) / mse_base
    out["mse_baseline_holdout_mean"] = float(np.mean((y_ho - y_ho.mean()) ** 2))
    return out


def agg(series: pd.Series) -> tuple[int, float, float]:
    vals = series.dropna()
    return len(vals), float(vals.median()), float(vals.mean())


def main() -> None:
    base = pd.read_csv(BASE, dtype={"bond_key": str, "stock_key": str})
    daily = load_daily()

    stability_rows, holdout_rows, display = [], [], []
    for item in base.to_dict("records"):
        key, name = item["bond_key"], item["bond_name"]
        rets = pair_returns(daily, key, item["stock_key"])
        row = {"bond_key": key}
        for w in WINDOWS:
            beta, r2 = beta_r2(rets, w)
            row[f"beta_{w}"] = round(beta, 6)
            row[f"r2_{w}"] = round(r2, 6)
        stats = holdout_stats(rets)
        holdout_rows.append({"bond_key": key,
                             "mse_baseline": stats["mse_baseline"],
                             "mse_model": stats["mse_model"],
                             "improvement_pct": stats["improvement_pct"]})
        stability_rows.append(row)
        display.append({"key": key, "name": name, "n": len(rets), **row,
                        "improvement_pct": stats["improvement_pct"],
                        "mse_base_ho": stats["mse_baseline_holdout_mean"]})

    stability = pd.DataFrame(stability_rows)
    holdout = pd.DataFrame(holdout_rows)
    OUTDIR.mkdir(parents=True, exist_ok=True)
    stab_path = OUTDIR / "window_stability.csv"
    hold_path = OUTDIR / "holdout_improvement.csv"
    stability.to_csv(stab_path, index=False, encoding="utf-8")
    holdout.to_csv(hold_path, index=False, encoding="utf-8")

    disp = pd.DataFrame(display)
    print(f"B2 holdout & windows: wrote {stab_path.name}, {hold_path.name} "
          f"in {OUTDIR} ({len(stability)} bonds)")

    # ---- 主PPT p28: three-window beta/R2 side by side --------------------
    print(f"\n== 主PPT p28 佐证: 同一样本三窗口 beta/R2 对照 "
          f"(last-n paired returns, beta=cov/var, R2=corr^2) ==")
    print(f"{'window':>6s} {'n_bonds':>7s} {'beta_med':>9s} {'beta_mean':>10s} "
          f"{'r2_med':>7s} {'r2_mean':>8s}")
    for w in WINDOWS:
        n, b_med, b_mean = agg(disp[f"beta_{w}"])
        _, r_med, r_mean = agg(disp[f"r2_{w}"])
        print(f"{w:>6d} {n:>7d} {b_med:9.4f} {b_mean:10.4f} "
              f"{r_med:7.4f} {r_mean:8.4f}")

    print("\nper-bond windows (NaN = window unavailable, e.g. 翔26 60 returns):")
    print(f"{'bond_key':10s} {'name':6s} {'n':>4s} "
          + " ".join(f"{'b'+str(w):>7s} {'r2':>6s}" for w in WINDOWS))
    for r in disp.itertuples():
        def cell(col):
            v = getattr(r, col)
            return "    nan" if np.isnan(v) else f"{v:7.3f}"
        def cellr(col):
            v = getattr(r, col)
            return "   nan" if np.isnan(v) else f"{v:6.3f}"
        print(f"{r.key:10s} {r.name:6s} {r.n:4d} "
              + " ".join(f"{cell('beta_'+str(w)):>7s} {cellr('r2_'+str(w)):>6s}"
                         for w in WINDOWS))

    # ---- 主PPT p34: holdout improvement vs the +36.9% claim --------------
    judged = holdout.dropna(subset=["improvement_pct"])
    n_j, med, mean = agg(judged.improvement_pct)
    beats = int((judged.improvement_pct > 0).sum())
    print(f"\n== 主PPT p34 佐证: 留出检验改进% "
          f"(120训练OLS vs 均值猜, 末60留出, 不含息口径) ==")
    print(f"judged bonds: {n_j} (需 120+60 配对收益; 翔26 60 配对收益 -> 不参与)")
    for r in holdout.itertuples():
        if np.isnan(r.improvement_pct):
            print(f"  {r.bond_key:10s} improvement_pct = nan (无 120/60 留出设计)")
        else:
            print(f"  {r.bond_key:10s} mse_baseline={r.mse_baseline:.3e} "
                  f"mse_model={r.mse_model:.3e} improvement={r.improvement_pct:+.2f}%")
    print(f"\naggregate improvement%: mean={mean:+.2f}  median={med:+.2f}  "
          f"(beats baseline: {beats}/{n_j})   主PPT p34 claim: +{PPT_CLAIM_PCT}%")

    # 口径 diagnostics: plausible alternative readings of "+36.9%"
    beats_only = judged.loc[judged.improvement_pct > 0, "improvement_pct"]
    pooled = 100 * (judged.mse_baseline.sum() - judged.mse_model.sum()) \
        / judged.mse_baseline.sum()
    ratio = 100 * (1 - judged.mse_model.mean() / judged.mse_baseline.mean())
    ho_mse = disp.set_index("bond_key").loc[judged.bond_key, "mse_base_ho"]
    ho_base = 100 * (judged.mse_baseline.values - ho_mse.values) / ho_mse.values
    print("口径对照 (若 mean/median 对不上 36.9%):")
    print(f"  beats-only(10/17) mean = {beats_only.mean():+.2f}%   "
          f"pooled-SSE = {pooled:+.2f}%   "
          f"1-mean(model)/mean(base) = {ratio:+.2f}%")
    print(f"  '均值猜'=holdout均值(口径变体): mean = {ho_base.mean():+.2f}%   "
          f"median = {float(np.median(ho_base)):+.2f}%")
    print("\nMetrics describe historical prices; they are not recommendations.")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    main()
