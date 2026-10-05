"""B2 linkage recovery: rebuild the lost B3 inputs (beta_120, r2_120, test_model_beats_mean).

The historical `work/B_methods/B3/results.csv` was lost with the old repository.
`src/bquant/weights/compose.py` expects it (columns beta_120 / r2_120 /
test_model_beats_mean, indexed by bond_key) to score D4 via
`linkage_score(beta_120 * r2_120, beats_mean)`.

Method recovered from surviving evidence:
- Regression (workbenches/B2/run.py): pair bond `close` with underlying stock
  `qfq_close` by date (inner join), take daily pct_change returns, keep the last
  120 paired returns; beta = cov(bond, stock) / var(stock), R2 = corr(bond, stock)^2.
  Guard: need >= 40 usable returns and positive stock variance, else NaN.
- Holdout test (README "OLS+HC3稳健标准误、120训练/60留出、双收益口径" and
  workbenches/B2/任务说明_评分版.md "120训练/60留出"): train OLS
  bond_ret ~ a + b*stock_ret on the 120 paired returns immediately preceding the
  final 60, then beat-flag = MSE(model) < MSE("均值猜" = train mean) on the
  final-60 holdout. HC3 only affects standard errors, not this comparison.
  Verified below: this rule reproduces compose.py's implied beat flags for all
  17 judged bonds (10/17 beat the baseline, matching 主PPT p28 不含息口径).
- 双收益口径 note: 主PPT p28 also reports 11/17 含息 (dirty price). The curated
  daily file has bond qfq_close = NaN (no accrued-interest series), so the 含息
  variant is NOT reproducible from available data; the clean (不含息) basis used
  by B2/compose is recovered here.
- SH:113703 翔26转债 has only 61 paired bars (60 returns): no 120-day window, so
  beta_120/r2_120 are NaN and test_model_beats_mean is False. Historical B3
  excluded it (主PPT p28 "翔26无120日窗口不入图"); compose.py falls back to
  D4=5.0 with empty link_note either way.

Outputs data/inputs/b3_linkage_recovered.csv (bond_key, beta_120, r2_120,
test_model_beats_mean) and prints a validation table against
results/weights/composite_scores.csv (link_note beta, link value) and
workbenches/B2/逐券价格解释表_v0.csv (近120配对日R2). No existing file is modified.

Run: python scripts/b2_linkage.py   (from b-quant/)
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
OUT = ROOT / "data" / "inputs" / "b3_linkage_recovered.csv"
COMPOSITE = ROOT / "results" / "weights" / "composite_scores.csv"
EXPLAIN = ROOT / "workbenches" / "B2" / "逐券价格解释表_v0.csv"

BETA_WINDOW = 120           # 120 paired daily returns required for beta/R2 (B3 window)
TRAIN_N, HOLD_N = 120, 60   # holdout-test design: 120 train / 60 holdout


def load_daily() -> pd.DataFrame:
    with gzip.open(DAILY, "rt", encoding="utf-8") as f:
        daily = pd.read_csv(f, dtype={"asset_key": str, "bond_key": str})
    daily["date"] = pd.to_datetime(daily["date"])
    for field in ("close", "qfq_close"):
        daily[field] = pd.to_numeric(daily[field], errors="coerce")
    return daily


def pair_returns(daily: pd.DataFrame, bond_key: str, stock_key: str) -> pd.DataFrame:
    """Full-history paired daily returns, columns [bond_ret, stock_ret]."""
    bond = daily[daily.asset_key == bond_key].sort_values("date")
    stock = daily[daily.asset_key == stock_key].sort_values("date")
    paired = bond[["date", "close"]].merge(
        stock[["date", "qfq_close"]], on="date", how="inner")
    returns = paired[["close", "qfq_close"]].pct_change().dropna()
    return returns


def beta_r2_120(returns: pd.DataFrame) -> tuple[float, float]:
    """B2 run.py estimator on the last 120 paired returns.

    B3 requires a full 120-return window (its semantic is the 120-day paired
    regression; 主PPT p26: 翔26无120日窗口不入图). The workbench's >=40 guard
    applies to B2's own evidence table, not to the B3 input, so anything short
    of BETA_WINDOW usable returns yields NaN — required to reproduce the
    archived composite (SH:113703 falls back to D4=5.0 with empty link_note).
    """
    tail = returns.tail(BETA_WINDOW)
    beta = r2 = float("nan")
    if len(tail) >= BETA_WINDOW and tail.qfq_close.var() > 0:
        beta = tail.close.cov(tail.qfq_close) / tail.qfq_close.var()
        r = tail.close.corr(tail.qfq_close)
        r2 = r * r
    return float(beta), float(r2)


def beats_holdout(returns: pd.DataFrame) -> bool:
    """Recovered B3 flag: OLS(intercept) on 120 train returns must beat the
    train-mean guess on MSE over the final 60 holdout returns."""
    if len(returns) < TRAIN_N + HOLD_N:
        return False
    y = returns.close.values
    x = returns.qfq_close.values
    y_tr, x_tr = y[-(TRAIN_N + HOLD_N):-HOLD_N], x[-(TRAIN_N + HOLD_N):-HOLD_N]
    y_ho, x_ho = y[-HOLD_N:], x[-HOLD_N:]
    if y_tr.var() == 0 or x_tr.var() == 0:
        return False
    coef, *_ = np.linalg.lstsq(np.column_stack([np.ones(TRAIN_N), x_tr]),
                               y_tr, rcond=None)
    pred = coef[0] + coef[1] * x_ho
    mse_model = float(np.mean((y_ho - pred) ** 2))
    mse_mean = float(np.mean((y_ho - y_tr.mean()) ** 2))
    return bool(mse_model < mse_mean)


def linkage_score(beta_r2: float, beats_mean: bool) -> float:
    """Verbatim from src/bquant/weights/compose.py (validation only)."""
    def _step(value, breaks):
        for threshold, score in breaks:
            if value <= threshold:
                return score
        return breaks[-1][1]

    base = _step(beta_r2, [(0.01, 1.5), (0.03, 2.5), (0.06, 3.5), (0.12, 5.0),
                           (0.20, 6.5), (0.30, 8.0), (float("inf"), 9.0)])
    return round(base * (1.0 if beats_mean else 0.85), 2)


def main() -> None:
    base = pd.read_csv(BASE, dtype={"bond_key": str, "stock_key": str})
    daily = load_daily()
    rows = []
    for item in base.to_dict("records"):
        rets = pair_returns(daily, item["bond_key"], item["stock_key"])
        beta, r2 = beta_r2_120(rets)
        beats = beats_holdout(rets) if not np.isnan(beta) else False
        rows.append({"bond_key": item["bond_key"],
                     "bond_name": item["bond_name"],
                     "paired_return_n": len(rets),
                     "beta_120": round(beta, 6), "r2_120": round(r2, 6),
                     "test_model_beats_mean": beats})
    frame = pd.DataFrame(rows)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    frame[["bond_key", "beta_120", "r2_120", "test_model_beats_mean"]].to_csv(
        OUT, index=False, encoding="utf-8")
    print(f"B2 linkage recovered: wrote {OUT} ({len(frame)} bonds)")

    # ---- validation ------------------------------------------------------
    comp = pd.read_csv(COMPOSITE).set_index("bond_key") if COMPOSITE.exists() else None
    expl = (pd.read_csv(EXPLAIN).set_index("债券唯一键")
            if EXPLAIN.exists() else None)
    print("\n== validation: recovered vs composite_scores.csv link_note/link "
          "and 逐券价格解释表 近120配对日R2 ==")
    hdr = (f"{'bond_key':10s} {'name':6s} {'n':>4s} {'beta':>7s} {'noteβ':>6s} "
           f"{'dβ':>7s} {'r2':>6s} {'tabR2':>6s} {'dR2':>7s} {'beats':>5s} "
           f"{'link_calc':>9s} {'link_csv':>8s} {'ok':>3s}")
    print(hdr)
    n_beta_ok = n_r2_ok = n_link_ok = n_judged = n_r2_cmp = 0
    for row in rows:
        key, name = row["bond_key"], row["bond_name"]
        beta, r2, beats = row["beta_120"], row["r2_120"], row["test_model_beats_mean"]
        note_beta = d_beta = tab_r2 = d_r2 = None
        link_calc = link_csv = None
        ok = True
        if comp is not None and key in comp.index:
            note = comp.loc[key, "link_note"]
            if isinstance(note, str) and note.startswith("β"):
                note_beta = float(note[1:])
                d_beta = beta - note_beta
                if abs(d_beta) <= 0.005:
                    n_beta_ok += 1
                else:
                    ok = False
            link_csv = float(comp.loc[key, "link"])
            if not np.isnan(beta):
                link_calc = linkage_score(beta * r2, beats)
                n_judged += 1
                if abs(link_calc - link_csv) < 1e-9:
                    n_link_ok += 1
                else:
                    ok = False
            else:  # compose fallback reproduced (D4=5.0, empty note)
                link_calc = 5.0
                if link_csv == 5.0 and (not isinstance(comp.loc[key, "link_note"], str)
                                        or comp.loc[key, "link_note"] == ""):
                    n_link_ok += 1
                else:
                    ok = False
        if expl is not None and key in expl.index:
            tab_r2 = float(expl.loc[key, "近120配对日R2"])
            if not np.isnan(r2):
                d_r2 = r2 - tab_r2
                n_r2_cmp += 1
                if abs(d_r2) <= 0.0005 + 1e-9:
                    n_r2_ok += 1
                else:
                    ok = False
            # 翔26: table's R2 used its 60-obs window; B3 120-day window absent -> n/a
        fmt = lambda v, w, p: ("" if v is None else f"{v:{w}.{p}f}")
        beta_s = "    nan" if np.isnan(beta) else f"{beta:7.3f}"
        r2_s = "   nan" if np.isnan(r2) else f"{r2:6.3f}"
        d_r2_s = "n/a" if d_r2 is None else f"{d_r2:7.4f}"
        print(f"{key:10s} {name:6s} {row['paired_return_n']:4d} "
              f"{beta_s:>7s} {fmt(note_beta, 6, 2):>6s} {fmt(d_beta, 7, 4):>7s} "
              f"{r2_s:>6s} {fmt(tab_r2, 6, 3):>6s} {d_r2_s:>7s} "
              f"{str(beats):>5s} {fmt(link_calc, 9, 2):>9s} {fmt(link_csv, 8, 2):>8s} "
              f"{'OK' if ok else 'XX':>3s}")
    beats_true = sum(1 for r in rows if r["test_model_beats_mean"])
    xx = next(r for r in rows if r["bond_key"] == "SH:113703")
    print(f"\nbeta vs link_note (±0.005): {n_beta_ok}/17   "
          f"r2 vs explanation table (±0.0005, 120-day window bonds): "
          f"{n_r2_ok}/{n_r2_cmp}   "
          f"link reproduced via linkage_score (incl. fallback): {n_link_ok}/18")
    print(f"beats=True count: {beats_true}/{n_judged} judged "
          f"(主PPT p28: 10/17 不含息)   "
          f"SH:113703 翔26转债: {xx['paired_return_n']} paired returns < 120 "
          f"-> beta_120/r2_120=NaN, beats=False (compose fallback D4=5.0, empty note; "
          f"its 60-obs window R2 {float(expl.loc['SH:113703', '近120配对日R2']):.3f} "
          f"matches the workbench table but is not a B3 input)")
    if COMPOSITE.exists():
        import hashlib
        print(f"composite_scores.csv untouched (sha256 {hashlib.sha256(COMPOSITE.read_bytes()).hexdigest()[:12]}…); "
              f"only {OUT} was written")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    main()
