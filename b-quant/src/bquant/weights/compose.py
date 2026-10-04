"""Compose the V6 D1-D6 scores, with red lines outside the weighted sum.

D1 经营与信用 = 0.6×经营方向分 + 0.4×信用分
D2 估值可兑现 = 溢价分段 + 树差修正
D3 债底保护 = 债底覆盖分
D4 正股走势与联动 = beta×R²分段，留出未过乘0.85
D5 流动性与路径 = 正股120日回撤分段 + 成交中位数三分位±0.5
D6 市场表现预测 = 0.4×P50映射 + 0.3×P5映射 + 0.3×亏损概率映射

Restores V6's actual scoring rules without revising their financial interpretation.
"""
from pathlib import Path
import json
from datetime import date
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]          # b-quant/
REPO = ROOT.parent                                   # bond-investment/
DATA = REPO / 'data' / 'curated'
PRED = ROOT / 'results' / 'predict' / 'predictions.csv'
WEIGHTS = ROOT / 'results' / 'weights' / 'weights.json'

O_MAP = [('正向', 8.8), ('中性偏正', 6.5), ('中性', 5.2), ('中性偏负', 3.5), ('负向', 1.0)]
RATING_BASE = {'AAA': 9.8, 'AA+': 9.0, 'AA': 8.5, 'AA-': 7.5, 'A+': 6.0, 'A': 4.5, 'BBB+': 3.0}
DOWNGRADE_PENALTY = 1.5
DIMS = ['D1', 'D2', 'D3', 'D4', 'D5', 'D6']

def _step(value, breaks):
    for threshold, score in breaks:
        if value <= threshold:
            return score
    return breaks[-1][1]

def operating_score(direction: str) -> float:
    for prefix, score in O_MAP:
        if str(direction).startswith(prefix):
            return score
    return 5.2

def credit_score(rating: str, rating_previous: str) -> float:
    base = RATING_BASE.get(str(rating).strip(), 5.0)
    return max(0.0, base - (DOWNGRADE_PENALTY if str(rating).strip() != str(rating_previous).strip() else 0.0))

def premium_score(premium_pct: float) -> float:
    return _step(premium_pct, [(20, 9.5), (40, 8.0), (60, 6.5), (80, 5.0), (100, 3.5), (150, 1.5), (float('inf'), 0.5)])

def debt_score(coverage: float) -> float:
    return _step(coverage, [(0.7, 2.0), (0.8, 3.5), (0.85, 5.0), (0.9, 6.0), (0.95, 7.0), (1.0, 8.0), (1.05, 9.0), (float('inf'), 10.0)])

def linkage_score(beta_r2: float, beats_mean: bool) -> float:
    base = _step(beta_r2, [(0.01, 1.5), (0.03, 2.5), (0.06, 3.5), (0.12, 5.0), (0.20, 6.5), (0.30, 8.0), (float('inf'), 9.0)])
    return round(base * (1.0 if beats_mean else 0.85), 2)

def drawdown_score(dd_fraction: float) -> float:
    pct = abs(dd_fraction) * 100
    return _step(pct, [(10, 9.0), (15, 8.0), (20, 6.5), (25, 4.5), (float('inf'), 2.5)])

def distribution_score(p50: float, p05: float, p_loss: float) -> float:
    m50 = _step(p50, [(-8, 2.0), (-4, 3.5), (0, 5.0), (3, 6.5), (8, 8.0), (float('inf'), 9.0)])
    m05 = _step(p05, [(-20, 2.0), (-10, 4.5), (0, 7.0), (float('inf'), 9.0)])
    mloss = _step(p_loss, [(10, 9.0), (25, 7.5), (40, 6.0), (60, 4.0), (float('inf'), 2.5)])
    return round(0.4 * m50 + 0.3 * m05 + 0.3 * mloss, 2)

def load_dimensions() -> pd.DataFrame:
    base = pd.read_csv(REPO / 'work' / 'B_methods' / 'B1' / 'base.csv')
    ares = pd.read_csv(REPO / 'work' / 'A' / 'results.csv').set_index('bond_key')
    b2 = pd.read_csv(REPO / 'work' / 'B_methods' / 'B2' / 'results.csv').set_index('bond_key')
    b3 = pd.read_csv(REPO / 'work' / 'B_methods' / 'B3' / 'results.csv').set_index('bond_key')
    daily = pd.read_csv(DATA / 'b_daily_group13_20200101_20260930.csv.gz')
    daily['date'] = pd.to_datetime(daily.date)
    pred = pd.read_csv(PRED)
    rows = []
    for b in base.itertuples():
        key = b.bond_key
        a_row = ares.loc[key]
        b2_row = b2.loc[key]
        b3_row = b3.loc[key] if key in b3.index else None
        premium = float(b.conversion_premium_pct)
        coverage = float(b2_row['debt_floor_200bp']) / float(b.bond_close)
        beats = bool(b3_row['test_model_beats_mean']) if b3_row is not None else False
        link_note = ''
        if b3_row is not None and pd.notna(b3_row['beta_120']) and pd.notna(b3_row['r2_120']):
            link = linkage_score(float(b3_row['beta_120']) * float(b3_row['r2_120']), beats)
            link_note = f"β{float(b3_row['beta_120']):.2f}"
        else:
            link = 5.0
        stock = daily[(daily.asset_key == b.stock_key) & (daily.asset_type == 'stock')].sort_values('date')
        last120 = stock.tail(120)
        peak = last120.qfq_close.cummax()
        dd = float((last120.qfq_close / peak - 1.0).min())
        bond_px = daily[(daily.asset_key == key) & (daily.asset_type == 'bond')].sort_values('date')
        med_vol = float(bond_px.tail(20).volume_lots.median()) if len(bond_px) else np.nan
        p = pred[(pred.bond_key == key) & (pred.method == 'bootstrap') & (pred.exit_basis == 'convergence') & (pred.spread_bp == 200)]
        if p.empty:
            p = pred[(pred.bond_key == key) & (pred.method == 'gbm') & (pred.exit_basis == 'convergence') & (pred.spread_bp == 200)]
        if p.empty:
            p = pred[(pred.bond_key == key) & (pred.method == 'maturity_payoff')]
        prow = p.iloc[0]
        oper, cred = operating_score(a_row['direction']), credit_score(a_row['rating'], a_row['rating_previous'])
        d1 = round(0.6 * oper + 0.4 * cred, 2)
        p_score = premium_score(premium)
        tree_gap = float(b2_row['tree_gap_pct'])
        if premium <= 80:
            p_score = float(np.clip(p_score + np.clip(tree_gap, -3, 3) * 0.4, 0, 10))
        redlines = []
        if str(a_row['rating']).strip() != str(a_row['rating_previous']).strip():
            redlines.append('R1 评级下调')
        if premium > 100:
            redlines.append('R2 溢价>100%')
        if len(bond_px) < 120:
            redlines.append('R3 样本<120条')
        maturity = date.fromisoformat(str(b2_row['maturity_date'])[:10])
        if maturity < date(2027, 3, 30):
            redlines.append('R3 期内到期')
        d5 = drawdown_score(dd)
        rows.append(dict(bond_key=key, bond_name=b.bond_name, direction=a_row['direction'],
                         rating=a_row['rating'], downgraded=str(a_row['rating']).strip() != str(a_row['rating_previous']).strip(),
                         premium=round(premium, 1),
                         D1=d1, D2=round(p_score, 2), D3=debt_score(coverage), D4=link, D5=round(d5, 2),
                         D6=distribution_score(float(prow['p50']), float(prow['p05']), float(prow['p_loss'])),
                         drawdown=round(dd * 100, 1), coverage=round(coverage, 3), med_vol_lots=med_vol,
                         link=link, link_note=link_note,
                         p50=float(prow['p50']), p05=float(prow['p05']), p_loss=float(prow['p_loss']),
                         redline='; '.join(redlines)))
    frame = pd.DataFrame(rows)
    vols = frame.med_vol_lots.dropna()
    med_vol_hi, med_vol_lo = vols.quantile([2 / 3, 1 / 3])
    frame['D5'] = (frame.D5 + frame.med_vol_lots.map(
        lambda v: 0.5 if v >= med_vol_hi else (-0.5 if v <= med_vol_lo else 0.0))).clip(0, 10).round(2)
    return frame

def compose(with_weights: dict[str, float] | None = None) -> pd.DataFrame:
    weights = with_weights if with_weights is not None else json.loads(WEIGHTS.read_text(encoding='utf-8'))['weights']['dimension']
    if set(weights) != set(DIMS) or any(not np.isfinite(w) or w < 0 for w in weights.values()) or not np.isclose(sum(weights.values()), 1.0):
        raise ValueError('V6 requires six nonnegative D1-D6 weights summing to 1')
    frame = load_dimensions()
    frame['composite'] = sum(frame[d] * weights[d] for d in DIMS).round(3)
    frame['redlined'] = frame.redline != ''
    frame = frame.sort_values('composite', ascending=False).reset_index(drop=True)
    frame['rank_all'] = frame.index + 1
    open_rank = frame[~frame.redlined].copy()
    open_rank['rank_open'] = range(1, len(open_rank) + 1)
    frame['rank_open'] = open_rank.set_index('bond_key').rank_open.reindex(frame.bond_key).values
    return frame

def two_step_decision(frame: pd.DataFrame, tree_gaps: dict[str, float]) -> dict:
    """Step1 补偿门槛：树差≥0且无红线→直接入池；Step2 权重排序补足三席。门槛者按树差降序在前。"""
    open_bonds = frame[~frame.redlined]
    gated = [k for k in open_bonds.bond_key if tree_gaps.get(k, -999) >= 0]
    gated.sort(key=lambda k: -tree_gaps[k])
    fill = [k for k in open_bonds.bond_key if k not in gated][:3 - len(gated)]
    picks = gated + fill
    order = [k for k in open_bonds.bond_key if k not in picks]
    return {'picks': picks, 'gated': gated, 'filled_by_score': fill,
            'PASS': set(picks) == {'SZ:123183', 'SH:113659', 'SH:111002'} and picks == ['SZ:123183', 'SH:113659', 'SH:111002']}
