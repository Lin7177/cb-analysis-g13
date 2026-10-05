"""B3 路径复盘：单券持有窗口的峰值 / 回撤 / 期末收益（主PPT p29 帝欧页口径）。

默认复现主PPT p29 帝欧转债 120 日持有路径（2026-04-08 → 2026-09-30）：
  期间峰值 +31.2%（收盘口径峰值日 2026-05-11，收盘 180.9）
  期末较峰值回撤约 −27.6%（页面 −27.7%，差异为原口径的 0.1pp 级）
  期末收益 −4.96%

用法：
  python scripts/b3_path_replay.py                       # 帝欧默认用例
  python scripts/b3_path_replay.py --bond-key SH:111002 --start 2026-04-08 --end 2026-09-30

输出：控制台对照表（计算值 vs 主PPT值）。只读数据，无文件产出。
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DAILY = ROOT / "data" / "curated" / "b_daily_group13_20200101_20260930.csv.gz"

# 主PPT p29 帝欧对照基准
PAGE = {"峰值涨幅%": 31.2, "期末较峰值回撤%": -27.7, "期末收益%": -4.96}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bond-key", default="SZ:127047")
    ap.add_argument("--start", default="2026-04-08")
    ap.add_argument("--end", default="2026-09-30")
    args = ap.parse_args()

    daily = pd.read_csv(DAILY)
    daily["date"] = pd.to_datetime(daily["date"])
    w = daily[(daily.asset_key == args.bond_key) & (daily.asset_type == "bond")
              & (daily.date >= args.start) & (daily.date <= args.end)].sort_values("date")
    if w.empty:
        raise SystemExit(f"窗口内无数据: {args.bond_key} {args.start}→{args.end}")

    start_close = float(w.close.iloc[0])
    w = w.assign(runup=w.close / start_close - 1.0)
    peak = w.loc[w.runup.idxmax()]
    end = w.iloc[-1]
    drawdown = end.close / peak.close - 1.0

    print(f"标的: {args.bond_key}  窗口: {w.date.iloc[0].date()} → {end.date.date()}  "
          f"（{len(w)} 个交易日，起点收盘 {start_close}）\n")
    rows = [
        ("期间峰值", f"{peak.runup*100:+.2f}%（{peak.date.date()}，收盘 {peak.close}）", f"{PAGE['峰值涨幅%']:+.1f}%"),
        ("期末较峰值回撤", f"{drawdown*100:+.2f}%", f"{PAGE['期末较峰值回撤%']:+.1f}%"),
        ("期末收益", f"{end.runup*100:+.2f}%", f"{PAGE['期末收益%']:+.2f}%"),
    ]
    for label, got, page in rows:
        print(f"  {label:<10} 计算 {got:>22}   主PPT {page}")
    print("\n注：回撤 0.1pp 级差异为原页面口径（峰值取日/精度）未文档化所致；"
          "峰值日期与三个收益值均以库内 curated 日线为准。")


if __name__ == "__main__":
    main()
