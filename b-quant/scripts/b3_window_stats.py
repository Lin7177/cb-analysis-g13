"""B3 路径统计：四口径持有窗口对照（主PPT p29 窗口口径表的可复现实现）。

窗口定义（本脚本文档化的口径，此前未文档化——勘误 B6）：
- 窗口 = 同一只券债券日线中连续 120 个交易日；
- 期末收益 = 窗口末收盘 / 窗口首收盘 − 1（不复权口径，转债无复权）；
- 全历史：样本期内全部可能窗口（步长 1）；非重叠：窗口互不重叠（步长 = 120）；
- 近期：窗口结束日落在最后 252 个交易日内（约一个自然年）；
- 中位数 / 5% 分位：numpy median / quantile(0.05)。

默认券：帝欧转债 SZ:127047（主PPT p29 主体）。对照基准（主PPT p29 窗口口径表）：
  全历史·重叠 1052 样本｜中位 −2.0%｜5%分位 −23.6%
  全历史·非重叠 9｜中位 −2.0%
  近期·重叠 132｜中位 +4.7%｜5%分位 −0.9%
  近期·非重叠 2｜中位 +1.6%

用法： python scripts/b3_window_stats.py [--bond-key SZ:127047]
输出： results/path/window_stats.csv（口径、窗口数、中位、5%分位、对照与差异）+ 控制台对照表。
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DAILY = ROOT / "data" / "curated" / "b_daily_group13_20200101_20260930.csv.gz"
OUT = ROOT / "results" / "path" / "window_stats.csv"
WINDOW = 120
RECENT_BARS = 252

# 主PPT p29 对照基准（帝欧转债）
PAGE = {
    "全历史·重叠": (1052, -2.0, -23.6),
    "全历史·非重叠": (9, -2.0, None),
    "近期·重叠": (132, 4.7, -0.9),
    "近期·非重叠": (2, 1.6, None),
}


def window_returns(closes: pd.Series, step: int, recent_bars: int | None = None) -> np.ndarray:
    """120 日持有窗口的期末收益序列。step=1 重叠采样；step=WINDOW 非重叠。"""
    vals = closes.to_numpy()
    if recent_bars is not None:
        vals = vals[-recent_bars:]
    n = len(vals)
    out = []
    for i in range(0, n - WINDOW + 1, step):
        out.append(vals[i + WINDOW - 1] / vals[i] - 1.0)
    return np.array(out)


def summarize(returns: np.ndarray) -> tuple[int, float, float | None]:
    if len(returns) == 0:
        return 0, float("nan"), None
    q05 = float(np.quantile(returns, 0.05)) * 100 if len(returns) >= 5 else None
    return len(returns), float(np.median(returns)) * 100, q05


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bond-key", default="SZ:127047")
    args = ap.parse_args()

    daily = pd.read_csv(DAILY)
    daily["date"] = pd.to_datetime(daily["date"])
    bond = daily[(daily.asset_key == args.bond_key) & (daily.asset_type == "bond")].sort_values("date")
    closes = bond.set_index("date")["close"]
    name = f"{args.bond_key}（{len(closes)} 根日线）"
    print(f"标的: {name}  窗口长度: {WINDOW} 个交易日  近期边界: 最后 {RECENT_BARS} 个交易日\n")

    rows = []
    for label, step, recent in [
        ("全历史·重叠", 1, None),
        ("全历史·非重叠", WINDOW, None),
        ("近期·重叠", 1, RECENT_BARS),
        ("近期·非重叠", WINDOW, RECENT_BARS),
    ]:
        n, med, q05 = summarize(window_returns(closes, step, recent))
        p_n, p_med, p_q05 = PAGE[label]
        rows.append(dict(口径=label, 窗口数=n, 页面窗口数=p_n,
                         中位_pct=round(med, 2), 页面中位_pct=p_med,
                         分位5_pct=None if q05 is None else round(q05, 2),
                         页面5分位_pct=p_q05))

    out_df = pd.DataFrame(rows)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    out_df.to_csv(OUT, index=False, encoding="utf-8-sig")
    print(out_df.to_string(index=False))
    print(f"\n已写出: {OUT}")
    print("对照说明：样本数与中位/分位若与页面存在 ±3 / ±0.1~1.5pp 级差异，"
          "源于原页面窗口对齐口径未文档化（勘误 B6）；本脚本口径以 docstring 为准。")


if __name__ == "__main__":
    main()
