"""B1 底表与 A线打分文件恢复（b0-b4 前缀约定）。

恢复两份 compose.py 依赖但已失传的输入：
  (1) data/inputs/a_results_recovered.csv  —— A线打分（bond_key, direction, rating, rating_previous）
  (2) data/inputs/b1_base_recovered.csv    —— B1 底表（bond_key, stock_key, bond_name, bond_close, conversion_premium_pct）

数据来源（均为幸存资产，不改动任何现有文件）：
  - results/weights/composite_scores.csv ：冻结矩阵，取 direction / rating / downgraded 原文
  - data/curated/terms_verified.csv      ：核验后转股价（口径来源）
  - data/curated/b_daily_*.csv.gz        ：T日=2026-09-30 债/股收盘价
  - 主PPT个券页（sufe_ppt/slides/slide_08/10/13/21/22.html）：5 只降级券的降级前评级

构造口径：
  - conversion_value = stock_close(T) × 100 / conversion_price(terms_verified)
  - conversion_premium_pct = (bond_close(T) / conversion_value − 1) × 100   # 转股溢价率标准定义
  - rating_previous：降级券取主PPT个券页披露的降级前评级；未降级券 = rating

脚本同时做四重验证：
  V1 溢价复算 vs 冻结矩阵 premium 列（1位小数）
  V2 operating_score(direction) vs 冻结矩阵 S1 列
  V3 D1 = round(0.6×oper + 0.4×cred, 2)（compose.py v3.0 口径）vs 冻结矩阵 S1 列
  V4 S3 复算 = 0.6×cred + 0.4×debt_score(coverage) vs 冻结矩阵 S3 列（用降级前评级反证）
"""
from pathlib import Path
import sys

import pandas as pd

BQ = Path(__file__).resolve().parents[1]          # b-quant/
T_DAY = '2026-09-30'
FROZEN = BQ / 'results' / 'weights' / 'composite_scores.csv'
TERMS = BQ / 'data' / 'curated' / 'terms_verified.csv'
DAILY = BQ / 'data' / 'curated' / 'b_daily_group13_20200101_20260930.csv.gz'
CURATED_BASE = BQ / 'data' / 'curated' / 'base.csv'
OUT_DIR = BQ / 'data' / 'inputs'

sys.path.insert(0, str(BQ / 'src'))
from bquant.weights.compose import operating_score, credit_score, debt_score  # noqa: E402

# 主PPT个券页披露的降级前评级（A线已核实的 R1 红线券，共5只）
RATING_PREVIOUS_EVIDENCE = {
    'SZ:123154': ('AA-', "主PPT个券页 slide_22（火星）：『A+，自 AA- 下调，已核实』"),
    'SH:113625': ('AA-', "主PPT个券页 slide_10（江山）：『A，自 AA- 下调』"),
    'SZ:123235': ('AA-', "主PPT个券页 slide_21（亿田）：『AA- 降至 A+』"),
    'SZ:127047': ('A-',  "主PPT个券页 slide_13（帝欧）：『A- 降至 BBB+』"),
    'SZ:123229': ('A+',  "主PPT个券页 slide_08（艾录）：『2026 年 A，自 A+ 下调，已核实』"),
}


def main() -> None:
    frozen = pd.read_csv(FROZEN, encoding='utf-8-sig')
    terms = pd.read_csv(TERMS, encoding='utf-8-sig').set_index('bond_key')
    daily = pd.read_csv(DAILY)
    daily['date'] = daily['date'].astype(str)

    bond_close = (daily[(daily.date == T_DAY) & (daily.asset_type == 'bond')]
                  .set_index('asset_key')['close'])
    stock_close = (daily[(daily.date == T_DAY) & (daily.asset_type == 'stock')]
                   .set_index('asset_key')['close'])

    rows_base, rows_a, audit = [], [], []
    for r in frozen.itertuples():
        key = r.bond_key
        trow = terms.loc[key]
        conv_price = float(trow['conversion_price'])
        bc = float(bond_close.loc[key])
        sc = float(stock_close.loc[trow['stock_key']])
        conv_value = sc * 100.0 / conv_price
        premium = (bc / conv_value - 1.0) * 100.0

        rating = str(r.rating).strip()
        if key in RATING_PREVIOUS_EVIDENCE:
            rating_prev, evidence = RATING_PREVIOUS_EVIDENCE[key]
        else:
            rating_prev, evidence = rating, '未降级，rating_previous = rating'
        rows_a.append(dict(bond_key=key, direction=r.direction,
                           rating=rating, rating_previous=rating_prev))
        rows_base.append(dict(bond_key=key, stock_key=trow['stock_key'],
                              bond_name=trow['bond_name'], bond_close=bc,
                              conversion_premium_pct=round(premium, 6)))
        audit.append(dict(
            bond_key=key, bond_name=r.bond_name,
            conv_price=conv_price, stock_close=sc, bond_close=bc,
            conv_value=round(conv_value, 4),
            premium_calc=round(premium, 1), premium_frozen=float(r.premium),
            direction=r.direction, rating=rating, rating_prev=rating_prev,
            downgraded_frozen=str(r.downgraded) == 'True',
            downgraded_recovered=rating != rating_prev,
            oper=operating_score(r.direction),
            cred=credit_score(rating, rating_prev),
            S1=float(r.S1), S3=float(r.S3),
            coverage=float(r.coverage),
        ))

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    a_df = pd.DataFrame(rows_a)
    base_df = pd.DataFrame(rows_base)
    a_path = OUT_DIR / 'a_results_recovered.csv'
    base_path = OUT_DIR / 'b1_base_recovered.csv'
    a_df.to_csv(a_path, index=False, encoding='utf-8')
    base_df.to_csv(base_path, index=False, encoding='utf-8')

    aud = pd.DataFrame(audit)
    aud['D1_v3'] = (0.6 * aud.oper + 0.4 * aud.cred).round(2)
    aud['S3_recon'] = (0.6 * aud.cred + 0.4 * aud.coverage.map(debt_score)).round(6)

    ok = lambda mask: f'{int(mask.sum())}/{len(aud)}'

    print('=' * 100)
    print('产物')
    print('=' * 100)
    print(f'  {a_path.relative_to(BQ)}   rows={len(a_df)}')
    print(f'  {base_path.relative_to(BQ)} rows={len(base_df)}')

    print('=' * 100)
    print('V1 溢价复算 vs 冻结矩阵 premium（1位小数）:', ok(abs(aud.premium_calc - aud.premium_frozen) < 0.05))
    print('V2 operating_score(direction) vs 冻结 S1     :', ok(aud.oper == aud.S1))
    print('V3 D1(v3.0口径) vs 冻结 S1                  :', ok(aud.D1_v3 == aud.S1), '（预期判断见报告）')
    print('V4 S3复算(0.6cred+0.4debt) vs 冻结 S3       :', ok(abs(aud.S3_recon - aud.S3) < 1e-6))
    print('V5 downgraded 恢复 vs 冻结 downgraded       :', ok(aud.downgraded_recovered == aud.downgraded_frozen))

    if (CURATED_BASE.exists()):
        cb = pd.read_csv(CURATED_BASE, encoding='utf-8-sig').set_index('bond_key')
        joined = base_df.set_index('bond_key').join(cb[['bond_close', 'conversion_premium_pct']], rsuffix='_curated')
        px_ok = (joined.bond_close - joined.bond_close_curated).abs().lt(1e-9)
        pr_ok = (joined.conversion_premium_pct - joined.conversion_premium_pct_curated).abs().lt(1e-3)
        print('V6 bond_close 与 curated/base.csv 一致       :', ok(px_ok))
        print('V7 premium 与 curated/base.csv 核验值一致    :', ok(pr_ok))

    print('=' * 100)
    print('逐券对照表')
    print('=' * 100)
    show = aud[['bond_key', 'bond_name', 'direction', 'rating', 'rating_prev',
                'downgraded_frozen', 'conv_price', 'stock_close', 'bond_close',
                'conv_value', 'premium_calc', 'premium_frozen',
                'oper', 'cred', 'S1', 'D1_v3', 'S3_recon', 'S3']]
    show = show.copy()
    show['prem_ok'] = (show.premium_calc - show.premium_frozen).abs().lt(0.05)
    show['S1=oper'] = show.oper == show.S1
    show['S1=D1?'] = show.D1_v3 == show.S1
    show['S3_ok'] = (show.S3_recon - show.S3).abs().lt(1e-6)
    with pd.option_context('display.max_rows', None, 'display.max_columns', None,
                           'display.width', 250, 'display.max_colwidth', 22):
        print(show.to_string(index=False))

    print('=' * 100)
    print('降级券 rating_previous 证据（主PPT个券页）')
    print('=' * 100)
    for key, (prev, ev) in RATING_PREVIOUS_EVIDENCE.items():
        print(f'  {key}  previous={prev:<4} {ev}')

    mism = aud[aud.D1_v3 != aud.S1]
    if len(mism):
        print('-' * 100)
        print('V3 说明：S1 列与 v3.0 D1 口径不一致的券（S1 为 v2.0 体系"纯经营方向分"，非 0.6/0.4 合成）：')
        for m in mism.itertuples():
            print(f'  {m.bond_key} {m.bond_name:<6} direction={m.direction[:14]:<16} '
                  f'S1={m.S1:g}  oper={m.oper:g}  cred={m.cred:g}  D1(v3)={m.D1_v3:g}')


if __name__ == '__main__':
    main()
