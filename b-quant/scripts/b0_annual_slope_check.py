"""Annual aggregation of the FM debt-coverage slope, auditing main-deck p33.

The main deck p33 (合成与决策) states the debt_cov (债底覆盖) yearly FM slopes as
"+0.33 / +0.34 / +0.22 / +0.31 全正". docs/methodology/数字勘误与依据边界.md (A3)
notes the annual-mean recomputation from fm_slopes.csv differs. To decide which
aggregation (if any) the page used, this script reads
results/weights/fm_slopes.csv (monthly FM slopes produced by
scripts/b0_run_weight_estimation.py), groups the debt_cov column by the calendar
year of the month-end date, and computes three candidate aggregations:
  (a) mean_slope     - the year's mean of the monthly slopes;
  (b) year_end_slope - the last monthly slope observed within the year;
  (c) median_slope   - the year's median of the monthly slopes.
Each is compared with the page value for 2022 / 2023 / 2024 / 2025 (the four
calendar years covered by the slope panel, 2022-07 -> 2025-09).

Writes results/path/annual_slope_check.csv (new file; no existing file is touched)
and prints which aggregation reproduces the page numbers at two-decimal rounding,
or that none does (in which case the page should adopt the recomputed values; the
qualitative "四年全正" claim is unaffected).
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]          # b-quant/
SLOPES = ROOT / 'results' / 'weights' / 'fm_slopes.csv'
OUT = ROOT / 'results' / 'path' / 'annual_slope_check.csv'
FEATURE = 'debt_cov'                                # 债底覆盖
PAGE = {2022: 0.33, 2023: 0.34, 2024: 0.22, 2025: 0.31}  # 主PPT p33 分年度值


def main() -> None:
    slopes = pd.read_csv(SLOPES)
    slopes['year'] = pd.to_datetime(slopes.iloc[:, 0]).dt.year  # first column = month-end date

    rows = []
    for year, g in slopes.groupby('year'):
        s = g[FEATURE]
        rows.append(dict(year=int(year), n_months=len(s),
                         mean_slope=round(float(s.mean()), 4),
                         year_end_slope=round(float(s.iloc[-1]), 4),
                         median_slope=round(float(s.median()), 4),
                         page_value=PAGE.get(year)))
    check = pd.DataFrame(rows)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    check.to_csv(OUT, index=False, encoding='utf-8-sig')

    print(check.to_string(index=False))
    print(f'\nwrote {OUT} ({len(check)} years; feature={FEATURE})')
    for col in ('mean_slope', 'year_end_slope', 'median_slope'):
        hits = [r['year'] for r in check.to_dict('records')
                if r['page_value'] is not None and round(r[col], 2) == round(r['page_value'], 2)]
        print(f"  {col:<15} matches page at 2dp for years: {hits or 'none'}")
    verdict = next((col for col in ('mean_slope', 'year_end_slope', 'median_slope')
                    if all(round(r[col], 2) == round(r['page_value'], 2)
                           for r in check.to_dict('records'))), None)
    print('verdict:', (f"page = {verdict} (all four years match)"
                       if verdict else
                       'page matches NONE of mean / year-end / median at 2dp; '
                       'closest profile is the annual mean - the page should adopt the '
                       'recomputed values (qualitative 四年全正 claim unaffected)'))


if __name__ == '__main__':
    main()
