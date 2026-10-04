"""Produce B3 full-pool observed downside and volume evidence.

Run from repository root: python work/B_methods/B3/run.py
Historical drawdown/volume are descriptive, not forecast loss or executable size.
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


def drawdown(prices: pd.Series) -> float:
    return float((prices / prices.cummax() - 1).min())


def main() -> None:
    base = pd.read_csv(BASE, dtype={"bond_key": str, "stock_key": str})
    with gzip.open(DAILY, "rt", encoding="utf-8") as f:
        daily = pd.read_csv(f, dtype={"asset_key": str})
    daily["date"] = pd.to_datetime(daily["date"])
    for field in ("close", "qfq_close", "volume_lots", "high", "low"):
        daily[field] = pd.to_numeric(daily[field], errors="coerce")
    out = []
    for item in base.to_dict("records"):
        bond = daily[daily.asset_key == item["bond_key"]].sort_values("date")
        stock = daily[daily.asset_key == item["stock_key"]].sort_values("date")
        prices = bond.close
        returns60 = prices.pct_change().dropna().tail(60)
        stock_returns60 = stock.qfq_close.pct_change().dropna().tail(60)
        vol20 = bond.volume_lots.tail(20)
        vol60 = bond.volume_lots.tail(60)
        range20 = (bond.high / bond.low - 1).tail(20)
        median_volume = float(vol20.median())
        out.append({
            "bond_key": item["bond_key"], "industry": item["industry"],
            "bond_trading_bars": len(bond),
            "bond_realized_vol_60_ann_pct": round(float(returns60.std(ddof=1) * np.sqrt(252) * 100), 2),
            "stock_realized_vol_60_ann_pct": round(float(stock_returns60.std(ddof=1) * np.sqrt(252) * 100), 2),
            "bond_max_drawdown_120_pct": round(100 * drawdown(prices.tail(120)), 2),
            "bond_worst_daily_return_120_pct": round(100 * float(prices.pct_change().dropna().tail(120).min()), 2),
            "bond_5pct_daily_return_60_pct": round(100 * float(returns60.quantile(0.05)), 2),
            "bond_volume_median_20_lots": round(median_volume, 1),
            "bond_volume_min_20_lots": float(vol20.min()),
            "bond_T_volume_over_median_20": round(float(vol20.iloc[-1] / median_volume), 2)
                if median_volume > 0 else np.nan,
            "bond_volume_zero_days_60": int((vol60 == 0).sum()),
            "bond_high_low_range_median_20_pct": round(100 * float(range20.median()), 2),
            "drawdown_window_n": min(len(prices), 120),
            "risk_window_short_120": len(prices) < 120,
            "real_amount_available": False,
        })
    result = pd.DataFrame(out)
    result.to_csv(HERE / "risk_v1.csv", index=False, encoding="utf-8-sig")
    fig, ax = plt.subplots(figsize=(7.5, 5.2))
    dots = ax.scatter(result.bond_max_drawdown_120_pct,
                      result.bond_volume_median_20_lots,
                      c=result.bond_realized_vol_60_ann_pct,
                      cmap="magma", s=66, edgecolor="white")
    for row in result.to_dict("records"):
        if row["bond_key"] in {"SZ:123235", "SZ:127047", "SZ:123229",
                                "SZ:123250", "SH:113703"}:
            ax.annotate(row["bond_key"].split(":")[1],
                        (row["bond_max_drawdown_120_pct"],
                         row["bond_volume_median_20_lots"]),
                        xytext=(4, 4), textcoords="offset points", fontsize=8)
    ax.set_yscale("log")
    ax.set(xlabel="Observed 120-session max drawdown (%)",
           ylabel="Median daily volume, last 20 sessions (lots, log scale)",
           title="Group 13: downside and trading activity")
    fig.colorbar(dots, ax=ax, label="60-session realized volatility, ann. (%)")
    fig.tight_layout()
    fig.savefig(HERE / "downside_volume_v1.png", dpi=180)
    plt.close(fig)
    print(f"B3: {len(result)} bonds; historical downside and volume evidence computed")


if __name__ == "__main__":
    main()
