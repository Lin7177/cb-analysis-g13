"""Create four one-time, fillable 18-bond review sheets; never overwrite edits.

Run from repository root: python work/B_methods/create_review_sheets.py
The v0 sheets are work queues, not signed B diagnosis or G1 inputs.
"""

from __future__ import annotations

import csv
from pathlib import Path


HERE = Path(__file__).resolve().parent


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_once(path: Path, rows: list[dict[str, str]]) -> None:
    if path.exists():
        raise FileExistsError(f"Refusing to overwrite member work: {path}")
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"Created {path.name}: {len(rows)} rows")


def main() -> None:
    base = read_csv(HERE / "B1" / "base_v1.csv")
    relative = {row["bond_key"]: row for row in read_csv(HERE / "B2" / "relative_v1.csv")}
    risk = {row["bond_key"]: row for row in read_csv(HERE / "B3" / "risk_v1.csv")}
    scenario = {row["bond_key"]: row for row in read_csv(HERE / "B4" / "scenario_v1.csv")}
    keys = {row["bond_key"] for row in base}
    if len(base) != 18 or any(set(table) != keys for table in (relative, risk, scenario)):
        raise ValueError("B module keys do not match the 18-bond universe")

    sources = {
        "SH:113633": {
            "已查公告与日期": "科沃斯关于不向下修正科沃转债转股价格的公告；2026-08-11",
            "已查原文链接": "https://static.cninfo.com.cn/finalpage/2026-08-11/1225466110.PDF",
            "公告所述转股价及生效日": "172.97；2026-07-08",
            "已查条款事件": "2026-08-11至2027-02-10不提出下修方案",
        },
        "SZ:127047": {
            "已查公告与日期": "帝欧转债可能满足赎回条件提示公告；2026-09-24",
            "已查原文链接": "https://epaper.cs.com.cn/zgzqb/html/2026-09/24/nw.D110000zgzqb_20260924_2-B024.htm",
            "公告所述转股价及生效日": "5.10；该公告未给出最近一次调整生效日",
            "已查条款事件": "截至2026-09-23已有10个交易日满足130%门槛；并非已触发15日条件",
        },
        "SZ:123235": {
            "已查公告与日期": "亿田智能关于不提前赎回亿田转债的公告；2026-09-23",
            "已查原文链接": "https://vip.stock.finance.sina.com.cn/corp/view/vCB_AllBulletinDetail.php?id=12619291&stockid=300911",
            "公告所述转股价及生效日": "21.31；该公告未给出最近一次调整生效日",
            "已查条款事件": "已触发赎回条件；董事会承诺2026-09-24至2026-12-23不提前赎回；原件待取",
        },
    }
    b1, b2, b3, b4 = [], [], [], []
    for row in base:
        key = row["bond_key"]
        r2, r3, r4 = relative[key], risk[key], scenario[key]
        common = {"债券唯一键": key, "债券简称": row["bond_name"]}
        b1.append({
            **common, "候选转股价": row["conversion_price_candidate"],
            **sources.get(key, {"已查公告与日期": "", "已查原文链接": "",
                                 "公告所述转股价及生效日": "", "已查条款事件": ""}),
            "从该公告至T日追溯记录": "", "T日有效转股价": "",
            "转股期与到期现金流来源": "", "强赎/回售/下修/余额来源": "",
            "与候选值差异及下游影响": "", "核验人": "", "复核人": "",
            "核验状态": "部分公告已查，待追溯至T" if key in sources else "待核验",
        })
        b2.append({
            **common, "近60日债价收益_pct": r2["bond_price_return_60_pct"],
            "近60日正股前复权收益_pct": r2["stock_qfq_return_60_pct"],
            "近120配对日R2": r2["daily_linkage_r2_120"],
            "债价历史分位样本数": r2["price_percentile_n"],
            "候选溢价率_pct": r2["conversion_premium_pct_candidate"],
            "价格位置支持证据": "", "最强反证及不可比项": "",
            "可证伪机制/需核事件": "", "对B逐券判断的影响": "",
            "研究员": "", "复核人": "", "研究状态": "待解释",
        })
        b3.append({
            **common, "近120日最大回撤_pct": r3["bond_max_drawdown_120_pct"],
            "回撤窗口条数": r3["drawdown_window_n"],
            "近60日年化历史波动_pct": r3["bond_realized_vol_60_ann_pct"],
            "近20日成交手数中位数": r3["bond_volume_median_20_lots"],
            "近20日成交手数最小值": r3["bond_volume_min_20_lots"],
            "真实成交额/价差及来源": "", "主要下行来源": "",
            "最强缓冲证据": "", "不利路径及失效条件": "",
            "退出能力结论或缺口": "", "对B逐券判断的影响": "",
            "研究员": "", "复核人": "", "研究状态": "待解释",
        })
        b4.append({
            **common, "候选当前溢价率_pct": r4["current_premium_pct_candidate"],
            "股跌20pct维持债价所需新增溢价_pp":
                r4["additional_premium_needed_if_stock_down_20_pp"],
            "历史回撤_pct": r4["historical_drawdown_120_pct"],
            "B1条款证据与版本": "", "B2价格信号": "", "B3风险反证": "",
            "核心冲突和机械情景假设": "", "裁决所需证据及改判条件": "",
            "模型适用/降级原因": "", "对B逐券判断的影响": "",
            "研究员": "", "复核人": "", "研究状态": "待交叉复核",
        })
    write_once(HERE / "B1" / "逐券公告核验表_v0.csv", b1)
    write_once(HERE / "B2" / "逐券价格解释表_v0.csv", b2)
    write_once(HERE / "B3" / "逐券风险解释表_v0.csv", b3)
    write_once(HERE / "B4" / "逐券冲突复核表_v0.csv", b4)


if __name__ == "__main__":
    main()
