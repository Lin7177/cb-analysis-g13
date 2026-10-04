# bquant — 第13组可转债量化研究（B线）

18只可转债 + 18只正股的量化研究仓库：权重量化（B0）、数据底座与定价（B1）、股债联动（B2）、
持有路径（B3）、六个月市场表现预测与合成决策（B4，历史block bootstrap + GBM副案 +
walk-forward校准）。观察日 **2026-09-30**，公开信息截止当日15:00。模块编号与主PPT讲述分工
一致（B0 权重量化 ｜ B1 数据底座+定价 ｜ B2 联动 ｜ B3 路径 ｜ B4 预测+合成），导航见根README。

## 模块结构

| 模块 | 内容 | 入口 | 结果 |
| --- | --- | --- | --- |
| B0 权重量化 | FM+RankIC 两分支各50%反推六维权重（Newey-West t 诊断，−15%止损标签） | `scripts/b0_run_weight_estimation.py` | `results/weights/`（weights.json、fm_slopes.csv、rank_ic.csv） |
| B1 数据底座+定价 | 44,077条真实日线（2020-01-01→2026-09-30）、18券核验条款、国债曲线（SHA-256清单）；真实现金流债底 + QuantLib TF/CRR美式转股树（401步收敛<0.17%） | `scripts/b1_collect_daily.py` 等采集三件；`src/bquant/pricing/model.py` | `data/curated/`；树差/债底数值 |
| B2 联动 | OLS+HC3稳健标准误、120训练/60留出、双收益口径 | 计算见 `workbenches/B2`（历史工作台） | 同左 |
| B3 路径 | 期末收益vs路径回撤、16组窗口对照、58次除息事件核对 | 计算见 `workbenches/B3` | 同左 |
| B4 预测+合成 | 退出价值曲面×block bootstrap（主）/零漂移GBM（副），双退出口径，walk-forward校准；18券×六维合成与两步决策 | `src/bquant/predict/run.py`；`scripts/b4_reconcile_v6.py`（对账） | `results/predict/predictions.csv`、`results/weights/composite_scores.csv` |

## 快速开始

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.lock   # 或 pip install -e .
.venv/Scripts/python src/bquant/predict/run.py             # 重算六个月预测分布+校准
.venv/Scripts/python -m unittest discover -s tests         # 不变式测试
```

全部计算离线可复算：输入文件的SHA-256记录在各模块manifest中，重跑结果逐字节一致（种子固定）。

## 六个月预测结果速览（2026-09-30 → 2027-03-30，bootstrap/收敛口径/200bp）

| 券 | T全价 | P5 | P50 | P95 | P(亏损) |
| --- | --- | --- | --- | --- | --- |
| 海顺转债 | 129.05 | -10.3% | +4.0% | +64.3% | 39% |
| 莱克转债 | 129.81 | -12.0% | +3.8% | +50.4% | 40% |
| 特纸转债 | 133.52 | -16.2% | -7.6% | +50.4% | 68% |
| 科沃转债 | 111.34 | -1.7% | -1.7% | -0.6% | 96% |
| 帝欧转债 | 131.00 | -11.2% | +3.4% | +60.7% | 43% |
| 亿田转债 | 181.60 | -22.0% | +10.6% | +85.6% | 35% |

> 完整口径（双退出基准×三档利差×双引擎、信用压力行、强赎区域概率、走查校准）见
> `results/predict/predictions.csv` 与 `docs/methods/b4-prediction.md`。模型含义与边界
> 必须与该文档一起阅读：固定转股价、无滚动强赎/主动下修、利差为分析者情景。

## 数据来源与许可

- 行情：腾讯公开K线接口（债/股日线，前复权）；条款与公告：巨潮资讯网；无风险曲线：中国债券信息网（T-1日17:30发布规则已核验）。
- 数据仅用于课程研究；代码以MIT许可发布（见仓库根目录 [LICENSE](../LICENSE)）。

## 已知边界（诚实清单）

1. 树定价不含中国滚动强赎、发行人主动下修、回售与随机违约——预测继承同一口径。
2. 信用利差50/200/500bp是分析者情景，不是评级校准的市场报价。
3. bootstrap重采样重叠历史，有效样本量小于路径数；walk-forward显示90%名义区间实测覆盖约72%（区间偏窄），校准结果如实保留。
4. 走查使用T日条款与T日曲线回溯历史（历史转股价序列不可得），为已声明近似。
5. 翔26仅61条报价：只出GBM参数化结果；乐歌2026-10-20到期：按兑付确定性处理。
