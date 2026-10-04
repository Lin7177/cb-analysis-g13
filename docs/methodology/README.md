# docs/ 目录导览

本目录承载项目的方法论文档与上位依据。**现行口径唯一基准是《维度体系章程 v3.0》**，它与 36 页终稿《可转债全量版.pptx》（`deck/`）逐页对齐。模块导航（B0–B4）见仓库根 README。

```
docs/
├── methodology/
│   ├── 维度体系章程.md              ← v3.0 现行：D1–D6 体系/权重方法/红线与两步决策/模块编号
│   ├── 研究框架v2-终稿对齐说明.md    ← 审计结论：框架原文哪些成立、哪些被终稿取代
│   ├── 交割与验收契约-v0.md         ← 文件命名/版本/字段契约（历史流程契约，work/ 路径已废弃）
│   ├── README.md                    ← 本文件
│   └── 历史存档-v2/                 ← 研究框架_v2、维度体系章程 v2.0 原文（只读存档，勿引用为现行口径）
└── course-requirements/
    ├── 小组作业.pptx                ← 课程原始作业要求（上位依据）
    └── convertible_bonds_groups_15.xlsx  ← 课程分组表
```

## 投资问题口径（全组统一，见主PPT p01/p02）

> **研究谁**：第 13 组 18 只转债（轻工制造 12 + 家用电器 6）。
> **回答什么**：面向不加杠杆、重视下行的二级市场投资者，以 **2026-09-30 收盘**价格与当日 15:00 前公开信息，判断未来约六个月（评价窗口至 2027-03-30）是否适合新增买入；最终 3 只推荐、3 只回避，均附可核验条件。
> **怎么答**：A 线（6 人）基本面与信用判断 + B 线（4 人）数据、测算与预测；测算归 B、打分归 A，红线一票否决。

## 数字谱系（一页速查）

```
b-quant/scripts/b1_collect_daily.py ──→ b-quant/data/curated/（44,077条日线，SHA-256 manifest）
        │
b-quant 管线（799券面板 → pricing 定价核 → B0 权重反推[FM+RankIC 50/50] → B4 bootstrap预测）
        │       results/weights/{weights.json, composite_scores.csv}
        │       results/predict/{predictions.csv, calibration.csv}
        └── b-quant/scripts/b4_reconcile_v6.py（权重再生成 + 与主PPT p32 矩阵对账）
                │
        deck/可转债全量版.pptx（36页终稿）
```

## 已知缺口（诚实声明，下一阶段处理）

1. ~~compose 重算路径断裂~~ **已闭合（2026-10-05）**：三份失传评分输入已恢复至 `b-quant/data/inputs/`（恢复脚本 `b1_price_bonds.py`/`b1_build_base.py`/`b2_linkage.py`，来历与验证见 [PROVENANCE.md](../../b-quant/data/inputs/PROVENANCE.md)）；compose 输出与主PPT p32 矩阵 18/18 吻合。注意 p32 综合列与 weights.json 分属综合/展示双口径（V6 已知设计，见 PROVENANCE）
2. **workbenches 目录编号与主PPT模块编号存在历史错位**（见章程 §五；各脚本已加历史冻结头注）
3. **公告证据原件不入库**：143MB 的 B1_verified 公告 PDF 留在老仓库 `data/cache/`，如需证据链可由 `b-quant/src/bquant/collect/` 采集脚本重新获取
4. 旧 G0 流程文档（可执行方案、报告蓝图、A负责人任务说明等）留在老仓库 `project_docs/`，未迁移
