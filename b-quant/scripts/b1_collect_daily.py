"""Collect and validate Group 13 public daily market bars. (B1 数据底座采集入口)

Run: python scripts/b1_collect_daily.py
Check saved output: python scripts/b1_collect_daily.py --validate-only

Historical note (2026-10-05): the universe path was repaired to the current
layout (data/universe_v1.csv). Actual (re)collection still requires network
access to the public Tencent endpoint; `--validate-only` works offline.

The endpoint is Tencent Finance's publicly reachable K-line service. The
unadjusted daily bar is retained for both asset types; stocks also receive a
front-adjusted bar for historical return calculations. Responses are cached
under ignored data/cache so an interrupted run can resume.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import requests


ROOT = Path(__file__).resolve().parents[1]
UNIVERSE = ROOT / "data" / "universe_v1.csv"
OUT_DIR = ROOT / "data" / "curated"
CACHE_DIR = ROOT / "data" / "cache" / "b_daily"
API = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
DEFAULT_END = "2026-09-30"
START_YEAR = 2020
FIELDS = (
    "date", "asset_key", "asset_type", "bond_key", "open", "high", "low",
    "close", "volume_lots", "qfq_open", "qfq_high", "qfq_low", "qfq_close",
)


def universe() -> list[dict]:
    with UNIVERSE.open("r", encoding="utf-8-sig", newline="") as f:
        source = list(csv.DictReader(f))
    if len(source) != 18:
        raise ValueError(f"Expected 18 Group 13 bonds, found {len(source)}")
    assets = []
    seen = set()
    for row in source:
        bond_key = row["债券唯一键"]
        for asset_type, key in (("bond", bond_key), ("stock", row["正股唯一键"])):
            if key in seen:
                raise ValueError(f"Duplicate asset key: {key}")
            seen.add(key)
            assets.append({"asset_key": key, "asset_type": asset_type, "bond_key": bond_key})
    return assets


def cache_path(asset_key: str, year: int, adjustment: str, end_date: str) -> Path:
    # Current-year snapshots must not be reused for a later observation date.
    # The first fixed snapshot already uses legacy year-only cache names.
    suffix = ("" if year < date.fromisoformat(end_date).year or end_date == DEFAULT_END
              else f"_{end_date.replace('-', '')}")
    return CACHE_DIR / f"{asset_key.replace(':', '_')}_{year}{suffix}_{adjustment}.json"


def fetch(asset_key: str, year: int, adjustment: str, end_date: str) -> list[list[str]]:
    path = cache_path(asset_key, year, adjustment, end_date)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    code = asset_key.replace(":", "").lower()
    last_day = min(f"{year}-12-31", end_date)
    param = f"{code},day,{year}-01-01,{last_day},300,{adjustment}"
    field = "qfqday" if adjustment == "qfq" else "day"
    error = None
    for attempt in range(4):
        try:
            response = requests.get(API, params={"param": param}, timeout=20,
                                    headers={"User-Agent": "Mozilla/5.0"})
            response.raise_for_status()
            payload = response.json()
            if payload.get("code") != 0:
                raise ValueError(f"API code {payload.get('code')}: {payload.get('msg')}")
            bars = payload.get("data", {}).get(code, {}).get(field, [])
            if not isinstance(bars, list):
                raise ValueError("Missing bar list")
            for bar in bars:
                if len(bar) < 6 or not f"{year}-01-01" <= bar[0] <= last_day:
                    raise ValueError(f"Invalid bar/date: {bar}")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(bars, ensure_ascii=False, separators=(",", ":")),
                            encoding="utf-8")
            return bars
        except (requests.RequestException, ValueError, KeyError) as exc:
            error = exc
            if attempt < 3:
                time.sleep(1.5 * 2**attempt)
    raise RuntimeError(f"Failed {asset_key} {year} {adjustment}: {error}")


def parse_bar(bar: list[str]) -> dict[str, str]:
    # Public service order: date, open, close, high, low, volume in lots.
    return {"date": bar[0], "open": bar[1], "close": bar[2],
            "high": bar[3], "low": bar[4], "volume_lots": bar[5]}


def validate_price(row: dict, prefix: str = "") -> None:
    op, hi, lo, cl = (Decimal(row[prefix + field])
                      for field in ("open", "high", "low", "close"))
    if min(op, hi, lo, cl) <= 0 or hi < max(op, cl) or lo > min(op, cl):
        raise ValueError(f"Invalid OHLC {row['asset_key']} {row['date']} {prefix}")


def build(end_date: str) -> tuple[list[dict], dict]:
    assets = universe()
    years = range(START_YEAR, date.fromisoformat(end_date).year + 1)
    jobs = [(asset["asset_key"], year, adjustment)
            for asset in assets for year in years
            for adjustment in (("bfq", "qfq") if asset["asset_type"] == "stock" else ("bfq",))]
    results = {}
    with ThreadPoolExecutor(max_workers=4) as executor:
        future_map = {executor.submit(fetch, key, year, adjustment, end_date):
                      (key, year, adjustment) for key, year, adjustment in jobs}
        for n, future in enumerate(as_completed(future_map), 1):
            job = future_map[future]
            results[job] = future.result()
            if n % 50 == 0 or n == len(jobs):
                print(f"Fetched {n}/{len(jobs)} symbol-year-series", flush=True)
    rows = []
    details = []
    for asset in assets:
        key = asset["asset_key"]
        raw = [parse_bar(bar) for year in years for bar in results[(key, year, "bfq")]]
        adjusted = {bar[0]: parse_bar(bar) for year in years
                    for bar in results.get((key, year, "qfq"), [])}
        seen_dates = set()
        for bar in raw:
            if bar["date"] in seen_dates:
                raise ValueError(f"Duplicate {key} {bar['date']}")
            seen_dates.add(bar["date"])
            row = {"asset_key": key, "asset_type": asset["asset_type"],
                   "bond_key": asset["bond_key"], **bar}
            if asset["asset_type"] == "stock":
                if bar["date"] not in adjusted:
                    raise ValueError(f"Missing adjusted price {key} {bar['date']}")
                adj = adjusted[bar["date"]]
                row.update({f"qfq_{field}": adj[field]
                            for field in ("open", "high", "low", "close")})
                validate_price(row, "qfq_")
            else:
                row.update({f"qfq_{field}": "" for field in ("open", "high", "low", "close")})
            validate_price(row)
            if Decimal(row["volume_lots"]) < 0:
                raise ValueError(f"Negative volume {key} {bar['date']}")
            rows.append(row)
        if not raw:
            raise ValueError(f"No bars for {key}")
        if asset["asset_type"] == "stock" and set(adjusted) != seen_dates:
            raise ValueError(f"Adjusted/unadjusted dates differ for {key}")
        ordered_dates = sorted(seen_dates)
        details.append({"asset_key": key, "asset_type": asset["asset_type"],
                        "bond_key": asset["bond_key"], "bars": len(raw),
                        "first_date": ordered_dates[0], "last_date": ordered_dates[-1],
                        "has_observation_date": end_date in seen_dates,
                        "bars_by_year": dict(sorted(Counter(d[:4] for d in seen_dates).items()))})
    rows.sort(key=lambda row: (row["date"], row["asset_key"]))
    retrieval_times = [cache_path(key, year, adjustment, end_date).stat().st_mtime
                       for key, year, adjustment in jobs]
    manifest = {"dataset": "Group 13 convertible bonds and underlying stocks daily bars",
                "observation_date": end_date,
                "start_date": f"{START_YEAR}-01-01",
                "source_retrieval_window_utc": [
                    datetime.fromtimestamp(t, timezone.utc).isoformat(timespec="seconds")
                    for t in (min(retrieval_times), max(retrieval_times))],
                "source": API,
                "request_pattern": "{exchange}{code},day,{year}-01-01,{year_end},300,{bfq|qfq}",
                "adjustment": "bfq = unadjusted; qfq = stock front-adjusted, snapshot-dependent",
                "volume_unit": "Public endpoint's native lot/hand count; bond lot=10 bonds and stock lot=100 shares for approximate unit conversion. Do not treat as exact traded shares or turnover.",
                "assets": len(assets), "rows": len(rows),
                "coverage": details}
    return rows, manifest


def write(rows: list[dict], manifest: dict, end_date: str) -> tuple[Path, Path]:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stem = f"b_daily_group13_20200101_{end_date.replace('-', '')}"
    csv_path = OUT_DIR / f"{stem}.csv.gz"
    manifest_path = OUT_DIR / f"{stem}.manifest.json"
    tmp_csv = csv_path.with_suffix(".csv.gz.tmp")
    with tmp_csv.open("wb") as raw_file:
        with gzip.GzipFile(fileobj=raw_file, mode="wb", filename="", mtime=0,
                           compresslevel=9) as compressed:
            with io.TextIOWrapper(compressed, encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=FIELDS, lineterminator="\n")
                writer.writeheader()
                writer.writerows(rows)
    tmp_csv.replace(csv_path)
    manifest["csv_sha256"] = hashlib.sha256(csv_path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                             encoding="utf-8")
    return csv_path, manifest_path


def validate_saved(end_date: str) -> None:
    stem = f"b_daily_group13_20200101_{end_date.replace('-', '')}"
    csv_path = OUT_DIR / f"{stem}.csv.gz"
    manifest_path = OUT_DIR / f"{stem}.manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if hashlib.sha256(csv_path.read_bytes()).hexdigest() != manifest["csv_sha256"]:
        raise ValueError("CSV checksum mismatch")
    with gzip.open(csv_path, "rt", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    if len(rows) != manifest["rows"] or len({r["asset_key"] for r in rows}) != 36:
        raise ValueError("Asset or row count mismatch")
    if len({(r["date"], r["asset_key"]) for r in rows}) != len(rows):
        raise ValueError("Duplicate asset-date key")
    for row in rows:
        validate_price(row)
        if row["asset_type"] == "stock":
            validate_price(row, "qfq_")
    print(f"PASS: {len(rows)} rows, 36 assets, checksum and OHLC valid")
    absent = [d["asset_key"] for d in manifest["coverage"] if not d["has_observation_date"]]
    print(f"Missing observation-date bars: {absent}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--end-date", default=DEFAULT_END)
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    date.fromisoformat(args.end_date)
    if not args.validate_only:
        rows, manifest = build(args.end_date)
        csv_path, manifest_path = write(rows, manifest, args.end_date)
        print(f"Saved {csv_path} and {manifest_path}")
    validate_saved(args.end_date)


if __name__ == "__main__":
    main()
