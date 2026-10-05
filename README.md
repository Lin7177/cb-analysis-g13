# cb-analysis-g13 · 可转换债券投资分析（第13组）

上海财经大学债券投资课程小组项目：对轻工制造 12 只 + 家用电器 6 只共 **18 只可转债**，回答一个统一投资问题，给出 **3 只推荐、3 只回避**，全部条件公开可核验。

**核心交付物：[deck/可转债全量版.pptx](deck/可转债全量版.pptx)（36 页，讲稿备注齐全）｜ [PDF 版](deck/可转债全量版.pdf)**

## 投资问题（全组统一口径）

> 面向不加杠杆、重视下行的二级市场投资者，以 **2026-09-30 收盘**价格与当日 15:00 前公开信息，判断未来约六个月（评价窗口至 2027-03-30）是否适合新增买入。

> **结论速览**：推荐 **海顺、莱克、特纸**，回避 **科沃、帝欧、亿田**——依据与条件见主PPT p03/p34/p35，数字链路见下方导航表与数字谱系。

## 目录导览（三区）

| 位置 | 内容 |
| --- | --- |
| `deck/` | **36 页终稿 PPT + PDF**（对外交付物） |
| `docs/` | 方法论（[维度体系章程 v3.0](docs/methodology/维度体系章程.md)）、研究框架对齐说明、课程原始要求、历史存档 |
| `b-quant/` | 量化引擎：数据面板、定价、权重反推、预测、结果文件（自足可复算，见 [b-quant/README.md](b-quant/README.md)） |

## B0–B4 模块导航（编号与主PPT讲述分工一致；D1–D6 为六维评分体系，定义见[维度体系章程](docs/methodology/维度体系章程.md)§一）

| 模块 | 职责 | 主PPT | 入口脚本（b-quant/scripts/） | 引擎代码 | 产出 |
| --- | --- | --- | --- | --- | --- |
| **B0 权重量化** | 六维权重由历史数据反推（Fama–MacBeth 回归 + RankIC/ICIR 两法各50%） | p04–p05 | `b0_run_weight_estimation.py` | `src/bquant/weights/`（estimate/features） | `results/weights/weights.json`、fm_slopes、rank_ic |
| **B1 数据底座+定价** | 日线/评级/面板采集；债底折现、树定价 | p25–p27 | `b1_collect_daily.py`、`b1_collect_cb_ratings.py`、`b1_export_market_panel.py` | `src/bquant/{collect,terms,market,pricing}/` + `data/` | `data/curated/`（SHA-256 manifest）、树差（模型参考价−市价）/债底数值 |
| **B2 联动** | 正股→债价传导（β×R²，D4 测算） | p28 | `b2_linkage.py`（恢复脚本） | `workbenches/B2/`（历史工作台） | `data/inputs/b3_linkage_recovered.csv` |
| **B3 路径** | 持有路径统计（回撤/窗口口径，D5 测算） | p29 | `b3_ex_dividend.py`、`b3_window_stats.py`、`b3_path_replay.py` | `workbenches/B3/`（历史工作台） | `results/path/`（除息 58/45/18、窗口表、单券路径复盘） |
| **B4 预测+合成** | 六只重点券分布预测；18券×六维合成与两步决策 | p30–p33 | `b4_reconcile_v6.py`（脚本冻结：对账复现见 [PROVENANCE](b-quant/data/inputs/PROVENANCE.md)） | `src/bquant/predict/` + `weights/compose` | `results/predict/`、`results/weights/composite_scores.csv` |

### B 线复现指引（B 组成员逐模块自检；均在 `b-quant/` 目录下执行）

| 模块 | 命令 | 输入 | 输出与预期校验 |
| --- | --- | --- | --- |
| B0 权重量化 | `python scripts/b0_run_weight_estimation.py` | `data/curated/market/` 面板 | `results/weights/` 与已提交版本**逐字节一致**（种子固定） |
| B1 底座 | `python scripts/b1_collect_daily.py --validate-only` | `data/universe_v1.csv` + curated | 44,077 行 / 36 标的 / 校验和 PASS（重采需联网，去掉开关） |
| B1 定价 | `python scripts/b1_price_bonds.py` | `data/curated/` 条款+曲线+日线 | `data/inputs/b2_pricing_recovered.csv`（18 券树差/债底，重写应逐字节一致） |
| B1 树收敛 | `python scripts/b1_tree_convergence.py` | 同上 | `results/pricing/tree_convergence.csv`（最大差 0.163%） |
| B2 联动 | `python scripts/b2_linkage.py` → `python scripts/b2_holdout_windows.py` | `data/curated/b_daily` | `data/inputs/b3_linkage_recovered.csv` + `results/linkage/`（β 对 link_note 17/17） |
| B3 路径 | `python scripts/b3_ex_dividend.py` / `b3_window_stats.py` / `b3_path_replay.py` | `data/curated` + terms_verified | `results/path/`：除息 58/45/18；窗口 1055/9/133/2；帝欧复盘三值命中 |
| B4 预测+合成 | `python src/bquant/predict/run.py` → `python -m unittest discover -s tests` | `data/curated/` | `results/predict/`（72% 覆盖）；测试预期 9 passed / 2 errors（见诚实边界） |
| 合成对账 | 方法见 [PROVENANCE](b-quant/data/inputs/PROVENANCE.md)（综合口径权重 + p32 真值逐格对账） | `data/inputs/` | 主PPT p32 18/18 吻合、两步决策海顺/莱克/特纸 |

冻结件：`b4_reconcile_v6.py` 与 `workbenches/` 的 run.py（老布局路径，勿直接运行）；两件证据采集器 `b1_collect_terms.py`、`a_collect_research.py` 需路径适配后联网使用（头注在案）。

## 数字谱系（每个数字怎么来的）

```
b-quant/scripts/b1_collect_daily.py ──→ b-quant/data/curated/（44,077条日线，SHA-256 manifest）
        │
b-quant 管线（799券面板 → pricing 定价核 → B0 权重反推[FM+RankIC 50/50] → B4 bootstrap预测）
        │
b-quant/results/weights/{weights.json, composite_scores.csv}
b-quant/results/predict/{predictions.csv, calibration.csv}
        │
deck/可转债全量版.pptx（p32 合成矩阵与 composite_scores.csv 由 b4_reconcile_v6.py 对账）
```

## 快速开始

```bash
cd b-quant
pip install -e . && pip install -r requirements.lock
python scripts/b0_run_weight_estimation.py     # B0：权重反推（种子固定，离线可复算）
python src/bquant/predict/run.py               # B4：六案预测分布+校准
python -m unittest discover -s tests           # 测试（预期 9 passed, 2 errors——error 为老仓库路径依赖，见诚实边界）
```

## 诚实边界（已知缺口）

- **评分链已闭合（2026-10-05）**：曾失传的三份评分输入已从库内资产复算恢复至 `b-quant/data/inputs/`（来历与验证见 [PROVENANCE.md](b-quant/data/inputs/PROVENANCE.md)）；`compose` 输出与主PPT p32 矩阵 **18/18 逐格吻合**（D1–D6/综合/红线/开放排名），两步决策复现海顺/莱克/特纸。注意 p32 综合列使用综合口径权重（resid 入回归），`weights.json` 为 p33 展示口径——V6 双口径为已知设计
- **A线"为什么"证据层已找回（2026-10-05）**：57 列完整打分依据表 `a_results_original.csv` 自老仓库 git 历史恢复，与重建版 18/18×3 交叉一致；同期恢复 A线解释层与两件证据采集器（`b1_collect_terms.py`、`a_collect_research.py`，内部为老布局路径，运行前需适配）
- **课程第二交付物**：课件要求课后提交**完整分析报告**（邮件）；成文底稿见 `docs/report/分析报告_评分版-v4.md`（中间历史口径，头注有说明），正式成文尚未交付
- `workbenches/` 全部 run.py 与 `b4_reconcile_v6.py` 按老仓库布局书写，当前**不可直接运行**（冻结说明见 workbenches/README 头注，待风格重构轮修复）；单测因此预期 **9 passed, 2 errors**。`b1_collect_daily.py` 路径已修复，离线自检可用（`--validate-only`），实际采集需联网
- 主PPT数字 ↔ 仓库证据的对账与勘误处置：[docs/methodology/数字勘误与依据边界.md](docs/methodology/数字勘误与依据边界.md)
- 本仓库自老仓库 bond-investment 迁移而来，完全独立、不含指向外部的路径引用；公告证据原件（143MB）不入库，可由 `src/bquant/collect/` 与 `b1_collect_terms.py` 采集脚本重新获取

## 许可

MIT（见 [LICENSE](LICENSE)）。数据仅用于课程研究。
