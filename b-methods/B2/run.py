"""Produce B2 full-pool relative-pricing and stock/bond linkage evidence.

Run from repository root: python work/B_methods/B2/run.py
Metrics describe historical prices; they are not recommendations.
"""

from __future__ import annotations

import gzip
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
DAILY = ROOT / "data" / "curated" / "b_daily_group13_20200101_20260930.csv.gz"
BASE = ROOT / "work" / "B_methods" / "B1" / "base_v1.csv"


def main() -> None:
    base = pd.read_csv(BASE, dtype={"bond_key": str, "stock_key": str})
    with gzip.open(DAILY, "rt", encoding="utf-8") as f:
        daily = pd.read_csv(f, dtype={"asset_key": str, "bond_key": str})
    daily["date"] = pd.to_datetime(daily["date"])
    for field in ("close", "qfq_close"):
        daily[field] = pd.to_numeric(daily[field], errors="coerce")
    out = []
    for item in base.to_dict("records"):
        bond = daily[daily.asset_key == item["bond_key"]].sort_values("date")
        stock = daily[daily.asset_key == item["stock_key"]].sort_values("date")
        paired = bond[["date", "close"]].merge(
            stock[["date", "qfq_close"]], on="date", how="inner",
            suffixes=("_bond", "_stock"))
        if paired.empty or paired.date.iloc[-1].strftime("%Y-%m-%d") != "2026-09-30":
            raise ValueError(f"Unpaired observation day: {item['bond_key']}")
        pair60 = paired.tail(61)
        bond_return60 = (pair60.close.iloc[-1] / pair60.close.iloc[0] - 1
                         if len(pair60) == 61 else np.nan)
        stock_return60 = (pair60.qfq_close.iloc[-1] / pair60.qfq_close.iloc[0] - 1
                          if len(pair60) == 61 else np.nan)
        returns = paired[["close", "qfq_close"]].pct_change().dropna().tail(120)
        beta = r2 = np.nan
        if len(returns) >= 40 and returns.qfq_close.var() > 0:
            beta = returns.close.cov(returns.qfq_close) / returns.qfq_close.var()
            r = returns.close.corr(returns.qfq_close)
            r2 = r * r
        history = bond.close.tail(252)
        pctile = 100 * (history <= history.iloc[-1]).sum() / len(history)
        out.append({
            "bond_key": item["bond_key"], "industry": item["industry"],
            "bond_close": item["bond_close"],
            "conversion_premium_pct_candidate": item["conversion_premium_pct_candidate"],
            "moneyness_stock_over_strike": item["moneyness_stock_over_strike"],
            "bond_price_percentile_252": round(pctile, 2),
            "price_percentile_n": len(history),
            "paired_trading_bars": len(paired),
            "bond_price_return_60_pct": round(100 * bond_return60, 2),
            "stock_qfq_return_60_pct": round(100 * stock_return60, 2),
            "daily_linkage_beta_120": round(beta, 3),
            "daily_linkage_r2_120": round(r2, 3),
            "daily_linkage_return_n": len(returns),
            "terms_status": item["terms_status"],
        })
    result = pd.DataFrame(out)
    result["premium_industry_percentile"] = result.groupby("industry")[
        "conversion_premium_pct_candidate"].rank(pct=True).mul(100).round(2)
    result.to_csv(HERE / "relative_v1.csv", index=False, encoding="utf-8-sig")
    fig, ax = plt.subplots(figsize=(7.5, 5.2))
    dots = ax.scatter(result.stock_qfq_return_60_pct,
                      result.bond_price_return_60_pct,
                      c=result.conversion_premium_pct_candidate,
                      cmap="viridis", s=66, edgecolor="white")
    for row in result.to_dict("records"):
        if row["bond_key"] in {"SZ:127047", "SZ:123235", "SZ:123154",
                                "SH:113633", "SZ:123072"}:
            ax.annotate(row["bond_key"].split(":")[1],
                        (row["stock_qfq_return_60_pct"], row["bond_price_return_60_pct"]),
                        xytext=(4, 4), textcoords="offset points", fontsize=8)
    ax.axhline(0, color="gray", lw=0.8)
    ax.axvline(0, color="gray", lw=0.8)
    ax.set(xlabel="Underlying stock 60-session QFQ return (%)",
           ylabel="Bond 60-session price return (%)",
           title="Group 13: stock-bond movement is not uniform")
    fig.colorbar(dots, ax=ax, label="Candidate conversion premium (%)")
    fig.tight_layout()
    fig.savefig(HERE / "stock_bond_60d_v1.png", dpi=180)
    plt.close(fig)
    print(f"B2: {len(result)} bonds; 60-session returns and 120-session linkage computed")


if __name__ == "__main__":
    main()
