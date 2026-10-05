"""B3 ex-dividend (annual coupon) event detection for the 18-bond pool.

Evidences the main-deck numbers on p25/p29: "核验现金流 108 笔 / 已核除息 58 次" and
"除息日价跌 45/58、现金票息翻正 18/58". These were previously recorded only in
workbenches/B1/任务说明_评分版.md, workbenches/B3/任务说明_评分版.md ("除息日价跌
45/58；价跌日加票息转正 18/58（口径：价跌且加票息后≥0）") and
docs/methodology/数字勘误与依据边界.md item B1; this script makes them reproducible
from curated data only.

口径 (conventions):
- Coupon calendar: terms_verified.csv gives 6 contractual cash flows per bond
  (18 x 6 = 108 flows in total - the p25 "核验现金流 108 笔" figure). Flow i
  (i = 1..6) is paid on the issue-date anniversary (a Feb-29 anniversary rolls back
  to Feb-28); the 6th flow coincides with maturity_date and is the redemption
  amount including the last coupon (no double counting of the final coupon).
- Coupon cash amount per 100 face = face(100) x coupon_rate(%)/100 / annual pay
  frequency; with annual pay (frequency = 1) this is numerically the stored rate
  itself (e.g. 1.5% -> 1.5 CNY per 100 face). All 18 bonds pay annually.
- Ex-dividend trading day: the CN convertible convention puts the record date on
  the last trading day before the payment date and the ex-date on the next
  session, so on bar data the drop lands between the last session strictly BEFORE
  the scheduled flow date (prev_close) and the first session ON/AFTER it
  (ex_close). A scheduled date on a weekend/holiday shifts the ex-date by 0-2
  sessions (observed over the 58 events: 40 same-day, 7 +1 day, 11 +2 days). A
  suspension spanning a coupon date would be absorbed by the same rule and flagged
  via prev_gap_days (largest gap in this pool is 4 calendar days, a holiday
  cluster; 永吉转债's 2022-05-19..25 suspension does not touch its April-14
  coupons).
- Detectable event = a scheduled flow with BOTH a prev session and an ex session
  inside the curated daily window (2020-01-01 -> 2026-09-30, per-bond bars, bond
  close is unadjusted full price per 100 face). Flows beyond the window (50 of the
  108) are skipped -> 58 detectable ex-dividend events.
- price_chg_pct  = (ex_close / prev_close - 1) x 100
- total_return_pct = (ex_close + coupon_per_100 - prev_close) / prev_close x 100
- Counts: events = 58; price_down = ex_close < prev_close -> 45; coupon_flip_nonneg
  = price_down AND total_return_pct >= 0 -> 18. The third number follows the B3
  workbench wording "价跌日加票息转正 18/58" - flips are counted only among the
  price-down events; counting coupon-inclusive non-negative returns across ALL 58
  events would give 31 (printed for reference only).

Writes results/path/dividend_events.csv (one row per detected event; new file, no
existing file is touched) and prints the summary against the 58/45/18 deck targets.
Observed-path evidence for the B3 module; not a forecast or recommendation.
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]          # b-quant/
sys.path.insert(0, str(ROOT / 'src'))
from bquant.terms import load_daily, load_terms

OUT = ROOT / 'results' / 'path' / 'dividend_events.csv'
WINDOWS = (date(2020, 1, 1), date(2026, 9, 30))     # curated daily-data window
TARGETS = dict(events=58, price_down=45, coupon_flips_nonneg=18)  # main deck p25/p29


def anniversary(issue: date, offset: int) -> date:
    """Issue-date anniversary `offset` years later; Feb-29 rolls back to Feb-28."""
    try:
        return issue.replace(year=issue.year + offset)
    except ValueError:
        return issue.replace(year=issue.year + offset, day=28)


def main() -> None:
    terms, daily = load_terms(), load_daily()
    bars = daily.loc[daily.asset_type == 'bond', ['date', 'asset_key', 'close']]

    rows = []
    for _, t in terms.iterrows():
        rates = json.loads(t['coupon_rates']) if isinstance(t['coupon_rates'], str) else t['coupon_rates']
        issue = date.fromisoformat(t['issue_date'])
        maturity = date.fromisoformat(t['maturity_date'])
        bond = bars.loc[bars.asset_key == t['bond_key']].sort_values('date').reset_index(drop=True)

        for seq, rate in enumerate(rates, start=1):
            scheduled = anniversary(issue, seq)
            if seq == len(rates):
                scheduled = maturity          # 6th flow = redemption incl. last coupon
            coupon = float(rate) * 100.0 / 100.0 / 1  # face(100) x rate% / 100 / annual freq
            prev = bond.loc[bond.date < pd.Timestamp(scheduled)]
            ex = bond.loc[bond.date >= pd.Timestamp(scheduled)]
            # Flow outside the observable window (before listing or after 2026-09-30).
            if prev.empty or ex.empty or not (WINDOWS[0] <= scheduled <= WINDOWS[1]):
                continue
            p, e = prev.iloc[-1], ex.iloc[0]
            prev_close, ex_close = float(p.close), float(e.close)
            price_chg = (ex_close / prev_close - 1) * 100
            total_ret = (ex_close + coupon - prev_close) / prev_close * 100
            rows.append(dict(
                bond_key=t['bond_key'], bond_name=t['bond_name'], coupon_seq=seq,
                scheduled_date=scheduled.isoformat(), ex_date=e['date'].date().isoformat(),
                prev_close=round(prev_close, 3), ex_close=round(ex_close, 3),
                coupon_per_100=round(coupon, 4),
                price_chg_pct=round(price_chg, 4), total_return_pct=round(total_ret, 4),
                price_down=bool(ex_close < prev_close),
                coupon_flip_nonneg=bool(ex_close < prev_close and total_ret >= 0),
                prev_gap_days=(pd.Timestamp(scheduled) - p['date']).days,
                ex_shift_days=(e['date'] - pd.Timestamp(scheduled)).days))

    events = pd.DataFrame(rows).sort_values(['bond_key', 'scheduled_date']).reset_index(drop=True)
    counts = dict(
        events=len(events),
        price_down=int(events.price_down.sum()),
        coupon_flips_nonneg=int(events.coupon_flip_nonneg.sum()),
    )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    events.to_csv(OUT, index=False, encoding='utf-8-sig')

    print(events[['bond_key', 'bond_name', 'coupon_seq', 'scheduled_date', 'ex_date',
                  'prev_close', 'ex_close', 'coupon_per_100',
                  'price_chg_pct', 'total_return_pct',
                  'price_down', 'coupon_flip_nonneg']].to_string(index=False))
    print(f"\nwrote {OUT} ({len(events)} events)")
    print('summary vs 主PPT p25/p29 targets:')
    for k, target in TARGETS.items():
        mark = 'HIT' if counts[k] == target else 'MISS'
        print(f"  {k:<22} = {counts[k]:>3}  (target {target:>3})  {mark}")
    print(f"  (reference) coupon-inclusive total_return_pct >= 0 across ALL events: "
          f"{int((events.total_return_pct >= 0).sum())}/{len(events)} "
          f"- the deck's 18/58 counts flips among price-down events only")
    print(f"  ex_shift_days distribution: {events.ex_shift_days.value_counts().sort_index().to_dict()}; "
          f"max prev_gap_days = {int(events.prev_gap_days.max())}")


if __name__ == '__main__':
    main()
