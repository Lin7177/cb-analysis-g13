# docs/ 目录导览

本目录承载项目的方法论文档与上位依据。**现行口径唯一基准是《维度体系章程 v3.0》**，它与 36 页终稿《可转债全量版.pptx》（`deck/`）逐页对齐。

```
docs/
├── methodology/
│   ├── 维度体系章程.md              ← v3.0 现行：D1–D6 体系/权重方法/红线与两步决策
│   ├── 研究框架v2-终稿对齐说明.md    ← 审计结论：框架原文哪些成立、哪些被终稿取代
│   ├── 交割与验收契约-v0.md         ← 文件命名/版本/字段契约（延续沿用）
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
scripts/collect_b_daily.py ──→ data/curated/（18券+18正股日线，SHA-256 manifest）
        │
b-quant/（B0面板 → pricing 定价核 → weights 权重反推[FM+RankIC 50/50] → predict[B4 bootstrap]）
        │       results/weights/{weights.json, composite_scores.csv}
        │       results/predict/{predictions.csv, calibration.csv}
        └── scripts/run_v6_scoring.py（权重再生成 + 与主PPT p32 矩阵对账）
                │
        deck/可转债全量版.pptx（36页终稿）
```

## 已知缺口（诚实声明，下一阶段处理）

1. **compose 重算路径断裂**：`b-quant/src/bquant/weights/compose.py` 期望的外部输入（A线打分 results.csv、B2/B3 results.csv）未随历史入库；现库中 `composite_scores.csv`（2026-10-03 生成）为准，`run_v6_scoring.py` 负责权重再生成与矩阵对账
2. **b-methods 目录编号与主PPT模块编号存在历史错位**（见章程 §五）
3. **公告证据原件不入库**：143MB 的 B1_verified 公告 PDF 留在旧仓库 `data/cache/`，如需证据链可由 `b-quant/src/bquant/collect/` 采集脚本重新获取
4. 旧 G0 流程文档（可执行方案、报告蓝图、A负责人任务说明等）留在老仓库 `project_docs/`，未迁移
