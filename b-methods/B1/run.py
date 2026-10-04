"""Build B1's 18-bond observation-day base from public data.

Run from repository root: python work/B_methods/B1/run.py
Public provider terms are candidates until issuer disclosures verify their
effective dates. --refresh ignores the cached provider response.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import requests
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
UNIVERSE = ROOT / "work" / "universe_v1.csv"
DAILY = ROOT / "data" / "curated" / "b_daily_group13_20200101_20260930.csv.gz"
CACHE = ROOT / "data" / "cache" / "B1" / "eastmoney_cb_pages.json"
API = "https://datacenter-web.eastmoney.com/api/data/v1/get"
T = "2026-09-30"
QUOTE_COLUMNS = (
    "f2~01~CONVERT_STOCK_CODE~CONVERT_STOCK_PRICE,"
    "f235~10~SECURITY_CODE~TRANSFER_PRICE,"
    "f236~10~SECURITY_CODE~TRANSFER_VALUE,"
    "f2~10~SECURITY_CODE~CURRENT_BOND_PRICE,"
    "f237~10~SECURITY_CODE~TRANSFER_PREMIUM_RATIO,"
    "f239~10~SECURITY_CODE~RESALE_TRIG_PRICE,"
    "f240~10~SECURITY_CODE~REDEEM_TRIG_PRICE,"
    "f23~01~CONVERT_STOCK_CODE~PBV_RATIO"
)


def get_page(page: int) -> dict:
    params = {"sortColumns": "PUBLIC_START_DATE", "sortTypes": "-1",
              "pageSize": "500", "pageNumber": str(page),
              "reportName": "RPT_BOND_CB_LIST", "columns": "ALL",
              "quoteColumns": QUOTE_COLUMNS, "source": "WEB", "client": "WEB"}
    error = None
    for attempt in range(3):
        try:
            r = requests.get(API, params=params, timeout=40,
                             headers={"User-Agent": "Mozilla/5.0"})
            r.raise_for_status()
            payload = r.json()
            if not payload.get("result") or not payload["result"].get("data"):
                raise ValueError(f"Empty provider page {page}")
            return payload
        except (requests.RequestException, ValueError) as exc:
            error = exc
            if attempt < 2:
                time.sleep(2**attempt)
    raise RuntimeError(f"Provider page {page} failed: {error}")


def provider_snapshot(refresh: bool) -> tuple[list[dict], str]:
    if CACHE.exists() and not refresh:
        saved = json.loads(CACHE.read_text(encoding="utf-8"))
        return saved["rows"], saved["retrieved_at_utc"]
    first = get_page(1)
    pages = first["result"]["pages"]
    result_pages = {1: first}
    if pages > 1:
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = {executor.submit(get_page, page): page for page in range(2, pages + 1)}
            for future in as_completed(futures):
                result_pages[futures[future]] = future.result()
    rows = [row for page in range(1, pages + 1)
            for row in result_pages[page]["result"]["data"]]
    retrieved_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps({"retrieved_at_utc": retrieved_at, "rows": rows},
                                ensure_ascii=False), encoding="utf-8")
    return rows, retrieved_at


def decimal(value) -> Decimal | None:
    if value in (None, "", "-"):
        return None
    return Decimal(str(value))


def fmt(value: Decimal | None, digits: int = 4) -> str:
    return "" if value is None else f"{value:.{digits}f}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()
    with UNIVERSE.open(encoding="utf-8-sig", newline="") as f:
        universe = list(csv.DictReader(f))
    with gzip.open(DAILY, "rt", encoding="utf-8", newline="") as f:
        daily = list(csv.DictReader(f))
    by_key = {}
    for row in daily:
        info = by_key.setdefault(row["asset_key"], {"count": 0})
        info["count"] += 1
        if row["date"] == T:
            info["t"] = row
    provider, retrieved_at = provider_snapshot(args.refresh)
    wanted = {row["债券代码"] for row in universe}
    matching = [row for row in provider if str(row.get("SECURITY_CODE")) in wanted]
    if len(matching) != 18 or len({row["SECURITY_CODE"] for row in matching}) != 18:
        raise ValueError(f"Provider matched {len(matching)} rows, expected 18 unique bonds")
    by_code = {str(row["SECURITY_CODE"]): row for row in matching}
    raw_fields = ("SECURITY_CODE", "CONVERT_STOCK_CODE", "CURRENT_BOND_PRICE",
                  "CONVERT_STOCK_PRICE", "TRANSFER_PRICE", "TRANSFER_VALUE",
                  "TRANSFER_PREMIUM_RATIO", "BOND_EXPIRE", "RATING",
                  "ACTUAL_ISSUE_SCALE", "COUPON_IR", "REDEEM_TRIG_PRICE",
                  "RESALE_TRIG_PRICE", "LISTING_DATE")
    snapshot_rows = []
    base_rows = []
    for item in universe:
        key, stock_key, code = (item["债券唯一键"], item["正股唯一键"], item["债券代码"])
        source = by_code[code]
        if str(source.get("CONVERT_STOCK_CODE")) != item["正股代码"]:
            raise ValueError(f"Stock mapping mismatch for {key}")
        bond = by_key[key]["t"]
        stock = by_key[stock_key]["t"]
        bond_close, stock_close, conversion_price = (
            Decimal(bond["close"]), Decimal(stock["close"]), decimal(source["TRANSFER_PRICE"]))
        if conversion_price is None or conversion_price <= 0:
            raise ValueError(f"Invalid conversion price for {key}")
        quote_bond, quote_stock = (decimal(source["CURRENT_BOND_PRICE"]),
                                   decimal(source["CONVERT_STOCK_PRICE"]))
        quote_match = (quote_bond is not None and quote_stock is not None
                       and abs(quote_bond - bond_close) <= Decimal("0.001")
                       and abs(quote_stock - stock_close) <= Decimal("0.01"))
        parity = Decimal(100) * stock_close / conversion_price
        premium_pct = Decimal(100) * (bond_close / parity - 1)
        provider_parity = decimal(source["TRANSFER_VALUE"])
        provider_premium = decimal(source["TRANSFER_PREMIUM_RATIO"])
        formula_match = (provider_parity is not None and provider_premium is not None
                         and abs(provider_parity - parity) <= Decimal("0.02")
                         and abs(provider_premium - premium_pct) <= Decimal("0.10"))
        snapshot_rows.append({"bond_key": key, "retrieved_at_utc": retrieved_at,
                              "source_url": API, **{field: source.get(field) for field in raw_fields}})
        base_rows.append({
            "bond_key": key, "stock_key": stock_key, "bond_name": item["债券简称"],
            "industry": item["行业"], "observation_date": T,
            "bond_close": bond["close"], "stock_close": stock["close"],
            "bond_volume_lots": bond["volume_lots"],
            "stock_volume_lots": stock["volume_lots"],
            "bond_trading_bars": by_key[key]["count"],
            "stock_trading_bars": by_key[stock_key]["count"],
            "conversion_price_candidate": fmt(conversion_price, 2),
            "conversion_value_candidate": fmt(parity),
            "conversion_premium_pct_candidate": fmt(premium_pct, 2),
            "moneyness_stock_over_strike": fmt(stock_close / conversion_price),
            "bond_price_over_par": fmt(bond_close / Decimal(100)),
            "provider_quote_matches_T": str(quote_match).lower(),
            "provider_formula_matches": str(formula_match).lower(),
            "terms_status": "issuer_effective_date_unverified",
            "provider_retrieved_at_utc": retrieved_at,
        })
    HERE.mkdir(parents=True, exist_ok=True)
    for path, records in ((HERE / "terms_candidate_v1.csv", snapshot_rows),
                          (HERE / "base_v1.csv", base_rows)):
        with path.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(records[0]))
            writer.writeheader()
            writer.writerows(records)
    quote_matches = sum(row["provider_quote_matches_T"] == "true" for row in base_rows)
    formula_matches = sum(row["provider_formula_matches"] == "true" for row in base_rows)
    fig, ax = plt.subplots(figsize=(7.5, 5.2))
    x = [float(row["conversion_value_candidate"]) for row in base_rows]
    y = [float(row["bond_close"]) for row in base_rows]
    color = [float(row["conversion_premium_pct_candidate"]) for row in base_rows]
    dots = ax.scatter(x, y, c=color, cmap="viridis", s=62, edgecolor="white")
    for row, px, py in zip(base_rows, x, y):
        if row["bond_key"] in {"SH:113633", "SZ:127047", "SZ:123235", "SH:113703"}:
            ax.annotate(row["bond_key"].split(":")[1], (px, py), xytext=(4, 5),
                        textcoords="offset points", fontsize=8)
    ax.set(xlabel="Conversion value (CNY / 100 par)",
           ylabel="Bond close (CNY / 100 par)",
           title="Group 13: price structure at 2026-09-30 close")
    fig.colorbar(dots, ax=ax, label="Candidate conversion premium (%)")
    fig.tight_layout()
    fig.savefig(HERE / "price_structure_v1.png", dpi=180)
    plt.close(fig)
    print(f"B1: 18 rows; T quote matches {quote_matches}/18; formula matches {formula_matches}/18")
    if quote_matches != 18 or formula_matches != 18:
        raise ValueError("Provider snapshot failed full-pool reconciliation; terms remain unusable")


if __name__ == "__main__":
    main()
