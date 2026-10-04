"""Join B1–B4 evidence for the B lead's review; never auto-vote 3+3.

Run from repository root: python work/B_methods/build_evidence_board.py
The output is a review queue, not work/B_diagnostics_v1.csv or a G1 input.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd


HERE = Path(__file__).resolve().parent


def main() -> None:
    base = pd.read_csv(HERE / "B1" / "base_v1.csv", dtype={"bond_key": str})
    relative = pd.read_csv(HERE / "B2" / "relative_v1.csv", dtype={"bond_key": str})
    risk = pd.read_csv(HERE / "B3" / "risk_v1.csv", dtype={"bond_key": str})
    scenario = pd.read_csv(HERE / "B4" / "scenario_v1.csv", dtype={"bond_key": str})
    tables = [base, relative, risk, scenario]
    if any(len(t) != 18 or t.bond_key.nunique() != 18 for t in tables):
        raise ValueError("One B module does not have exactly 18 unique bond keys")
    keys = set(base.bond_key)
    if any(set(t.bond_key) != keys for t in tables[1:]):
        raise ValueError("B module bond sets differ")
    out = base[["bond_key", "bond_name", "industry", "bond_close", "stock_close",
                "conversion_price_candidate", "conversion_value_candidate",
                "conversion_premium_pct_candidate", "terms_status"]]
    out = out.merge(relative[["bond_key", "bond_price_return_60_pct",
                              "stock_qfq_return_60_pct", "daily_linkage_r2_120",
                              "price_percentile_n"]], on="bond_key", validate="one_to_one")
    out = out.merge(risk[["bond_key", "bond_max_drawdown_120_pct",
                          "bond_volume_median_20_lots", "risk_window_short_120"]],
                    on="bond_key", validate="one_to_one")
    out = out.merge(scenario[["bond_key",
                              "additional_premium_needed_if_stock_down_20_pp"]],
                    on="bond_key", validate="one_to_one")
    flags = []
    for row in out.to_dict("records"):
        issue = []
        if row["conversion_premium_pct_candidate"] >= 150:
            issue.append("高候选溢价需解释债性和条款")
        if row["daily_linkage_r2_120"] < 0.2:
            issue.append("近120日股债联动弱")
        if row["bond_max_drawdown_120_pct"] <= -20:
            issue.append("近120日历史回撤较深")
        if row["bond_volume_median_20_lots"] < 10000:
            issue.append("近20日成交手数较少")
        if row["risk_window_short_120"]:
            issue.append("转债历史不足120交易日")
        flags.append("；".join(issue) if issue else "常规交叉复核")
    out["automatic_review_flags_not_votes"] = flags
    out.to_csv(HERE / "evidence_board_v0.csv", index=False, encoding="utf-8-sig")
    print(f"B evidence board: {len(out)} unique bonds; no investment direction assigned")


if __name__ == "__main__":
    main()
