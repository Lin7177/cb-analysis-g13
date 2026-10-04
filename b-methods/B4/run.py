"""Produce B4 transparent conversion-parity sensitivity, not price forecasts.

Run from repository root: python work/B_methods/B4/run.py
Inputs use B1 provider candidate terms; issuer-effective dates remain unverified.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
B1 = ROOT / "work" / "B_methods" / "B1" / "base_v1.csv"
B2 = ROOT / "work" / "B_methods" / "B2" / "relative_v1.csv"
B3 = ROOT / "work" / "B_methods" / "B3" / "risk_v1.csv"


def main() -> None:
    base = pd.read_csv(B1)
    relative = pd.read_csv(B2)
    risk = pd.read_csv(B3)
    merged = base.merge(relative[["bond_key", "daily_linkage_beta_120",
                                  "bond_price_percentile_252", "premium_industry_percentile"]],
                        on="bond_key", validate="one_to_one")
    merged = merged.merge(risk[["bond_key", "bond_max_drawdown_120_pct",
                                "bond_volume_median_20_lots", "risk_window_short_120"]],
                          on="bond_key", validate="one_to_one")
    if len(merged) != 18:
        raise ValueError("B1/B2/B3 full-pool join did not yield 18 bonds")
    out = []
    for row in merged.to_dict("records"):
        price = float(row["bond_close"])
        parity = float(row["conversion_value_candidate"])
        premium = price / parity - 1
        # Exact algebra: premium needed at a stressed stock price to keep the
        # current bond price unchanged. This does not predict future premium.
        parity_down = parity * 0.8
        parity_up = parity * 1.2
        required_down = price / parity_down - 1
        required_up = price / parity_up - 1
        # An explicitly hypothetical premium-compression sensitivity, not a
        # modeled fair value. 10 percentage points is an analyst-set shock.
        compressed_premium = premium - 0.10
        flat_stock_compression_price = parity * (1 + compressed_premium)
        down_stock_compression_price = parity_down * (1 + compressed_premium)
        out.append({
            "bond_key": row["bond_key"], "industry": row["industry"],
            "bond_close": round(price, 3),
            "conversion_value_candidate": round(parity, 4),
            "current_premium_pct_candidate": round(100 * premium, 2),
            "parity_if_stock_down_20_pct": round(parity_down, 3),
            "parity_if_stock_up_20_pct": round(parity_up, 3),
            "premium_needed_to_hold_price_if_stock_down_20_pct": round(100 * required_down, 2),
            "premium_needed_to_hold_price_if_stock_up_20_pct": round(100 * required_up, 2),
            "additional_premium_needed_if_stock_down_20_pp": round(100 * (required_down - premium), 2),
            "illustrative_return_flat_stock_premium_minus_10pp_pct":
                round(100 * (flat_stock_compression_price / price - 1), 2),
            "illustrative_return_stock_down_20_premium_minus_10pp_pct":
                round(100 * (down_stock_compression_price / price - 1), 2),
            "historical_linkage_beta_120": row["daily_linkage_beta_120"],
            "historical_drawdown_120_pct": row["bond_max_drawdown_120_pct"],
            "volume_median_20_lots": row["bond_volume_median_20_lots"],
            "risk_window_short_120": row["risk_window_short_120"],
            "terms_status": row["terms_status"],
            "scenario_status": "mechanical_sensitivity_not_price_forecast",
        })
    pd.DataFrame(out).to_csv(HERE / "scenario_v1.csv", index=False,
                             encoding="utf-8-sig")
    fig, ax = plt.subplots(figsize=(7.5, 5.2))
    shocks = np.linspace(-0.2, 0.2, 81)
    selected = {"SZ:127047", "SH:111002", "SZ:123235", "SH:113633"}
    for row in out:
        if row["bond_key"] in selected:
            required = (row["bond_close"] /
                        (row["conversion_value_candidate"] * (1 + shocks)) - 1) * 100
            ax.plot(shocks * 100, required, label=row["bond_key"].split(":")[1])
    ax.axvline(0, color="gray", lw=0.8)
    ax.set(xlabel="Illustrative stock-price change (%)",
           ylabel="Premium needed to keep today's bond price (%)",
           title="Group 13: required-premium sensitivity, not forecast")
    ax.legend(title="Bond code")
    fig.tight_layout()
    fig.savefig(HERE / "required_premium_sensitivity_v1.png", dpi=180)
    plt.close(fig)
    print(f"B4: {len(out)} bonds; parity and explicit premium-shock sensitivities computed")


if __name__ == "__main__":
    main()
