"""Cross-module QA for the fixed Group 13 B research workbench.

Run from repository root: python work/B_methods/verify.py
"""

from __future__ import annotations

import csv
import gzip
from decimal import Decimal
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
T = "2026-09-30"


def read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def main() -> None:
    with gzip.open(ROOT / "data" / "curated" /
                   "b_daily_group13_20200101_20260930.csv.gz", "rt",
                   encoding="utf-8", newline="") as f:
        daily = list(csv.DictReader(f))
    if max(row["date"] for row in daily) != T:
        raise ValueError("Daily data exceed or miss the observation date")
    t_prices = {row["asset_key"]: Decimal(row["close"])
                for row in daily if row["date"] == T}
    if len(t_prices) != 36:
        raise ValueError("Observation-day bond/stock coverage is not 36")
    paths = {"B1": "base_v1.csv", "B2": "relative_v1.csv",
             "B3": "risk_v1.csv", "B4": "scenario_v1.csv"}
    tables = {module: read_csv(HERE / module / filename)
              for module, filename in paths.items()}
    keys = {row["bond_key"] for row in tables["B1"]}
    if len(keys) != 18 or any(len(rows) != 18 or
                               {row["bond_key"] for row in rows} != keys
                               for rows in tables.values()):
        raise ValueError("B modules do not contain the same 18 unique bonds")
    review_paths = {"B1": "逐券公告核验表_v0.csv", "B2": "逐券价格解释表_v0.csv",
                    "B3": "逐券风险解释表_v0.csv", "B4": "逐券冲突复核表_v0.csv"}
    for module, filename in review_paths.items():
        rows = read_csv(HERE / module / filename)
        if len(rows) != 18 or {row["债券唯一键"] for row in rows} != keys:
            raise ValueError(f"{module} review sheet does not have the 18 unique bonds")
    base = {row["bond_key"]: row for row in tables["B1"]}
    scenario = {row["bond_key"]: row for row in tables["B4"]}
    for key in keys:
        row = base[key]
        if row["provider_quote_matches_T"] != "true" or row["provider_formula_matches"] != "true":
            raise ValueError(f"Public provider mismatch: {key}")
        if Decimal(row["bond_close"]) != t_prices[key]:
            raise ValueError(f"T bond price mismatch: {key}")
        if Decimal(row["stock_close"]) != t_prices[row["stock_key"]]:
            raise ValueError(f"T stock price mismatch: {key}")
        parity = Decimal(100) * Decimal(row["stock_close"]) / Decimal(row["conversion_price_candidate"])
        premium = (Decimal(row["bond_close"]) / parity - 1) * 100
        if abs(parity - Decimal(row["conversion_value_candidate"])) > Decimal("0.0001"):
            raise ValueError(f"Parity mismatch: {key}")
        if abs(premium - Decimal(row["conversion_premium_pct_candidate"])) > Decimal("0.01"):
            raise ValueError(f"Premium mismatch: {key}")
        required = (Decimal(row["bond_close"]) / (parity * Decimal("0.8")) - 1) * 100
        if abs(required - Decimal(scenario[key]["premium_needed_to_hold_price_if_stock_down_20_pct"])) > Decimal("0.02"):
            raise ValueError(f"B4 sensitivity mismatch: {key}")
    for module, filename in (("B1", "price_structure_v1.png"),
                             ("B2", "stock_bond_60d_v1.png"),
                             ("B3", "downside_volume_v1.png"),
                             ("B4", "required_premium_sensitivity_v1.png")):
        if (HERE / module / filename).stat().st_size < 10_000:
            raise ValueError(f"Missing or empty chart: {module}")
    print("PASS: 18/18 B1–B4 keys and review sheets, 36 T prices, parity/premium/scenario identities, four charts")


if __name__ == "__main__":
    main()
