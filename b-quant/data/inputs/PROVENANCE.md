# 评分输入恢复档案（PROVENANCE）

**日期**：2026-10-05
**背景**：`compose.py` 依赖的三份核心外部输入（A线打分、B2定价、B3联动）在老仓库中已失传，评分环节不可复算；随附恢复的还有一份底表（B1 base）。本档案记录恢复来源、方法与验证结论。

**现行模块对应**（文件名 b2_/b3_ 前缀沿用老仓库 work/B_methods 编号）：a_results → A线打分；b1_base → B1 底表；b2_pricing → B1 定价产出（主PPT p26/p27）；b3_linkage → B2 联动产出（主PPT p28）。

## 恢复的文件（本目录）

| 文件 | 内容 | 恢复方式 | 生成脚本 |
| --- | --- | --- | --- |
| `a_results_recovered.csv` | A线打分：direction / rating / rating_previous（18券） | direction/rating 逐字取自冻结矩阵 `results/weights/composite_scores.csv`；5 只降级券的降级前评级取自主PPT个券页（帝欧 A-→BBB+、艾录 A+→A、火星 AA-→A+、江山 AA-→A、亿田 AA-→A+） | `scripts/b1_build_base.py` |
| `b1_base_recovered.csv` | B1 底表：bond_key / stock_key / bond_name / bond_close[T日] / conversion_premium_pct | T日收盘取自 `data/curated/b_daily`，转股价取 `terms_verified.csv` 核验值，溢价=债收盘/转股价值−1 | `scripts/b1_build_base.py` |
| `b2_pricing_recovered.csv` | B2 定价：debt_floor_200bp / tree_gap_pct / tree_value / maturity_date | 库内定价核 `src/bquant/pricing/model.py`（CRR树401步+200bp债底折现），口径对齐 `predict/run.py` | `scripts/b1_price_bonds.py` |
| `b3_linkage_recovered.csv` | B3 联动：beta_120 / r2_120 / test_model_beats_mean | 120日债/股配对日收益回归（方法复刻自 workbenches/B2/run.py）；beats=120训练/60留出 OLS 优于均值基准 | `scripts/b2_linkage.py` |

## 验证结论

### 分项验证（对照幸存真值）

| 验证 | 结果 |
| --- | --- |
| 溢价复算 vs 冻结 premium 列 | 18/18 |
| debt_floor/市价 vs 冻结 coverage 列（3位小数） | 18/18 |
| 树差 vs 主PPT个券页真值（海顺+4.9/莱克+2.7/特纸−5.0 等） | 18/18 符号一致，最大偏差 0.05pp |
| beta vs 冻结 link_note（±0.005） | 17/17（翔26 无120日窗口，NaN 兜底） |
| R² vs workbenches 逐券解释表 | 17/17 |
| beats 判定 | 10/17 胜出，与主PPT p28 一致 |
| rating_previous（经 S3 口径反向验证） | 18/18 |

### 端到端验证（恢复输入 → compose → 主PPT p32）

以综合口径权重加权后，`compose()` 输出与 `results/reconciliation/v6_slide31_matrix.json`（v6 slide31 与主PPT p32 逐格一致的提取真值）对比：

**D1–D6 六维 18/18 ｜ 综合分 18/18 ｜ 红线 18/18 ｜ 开放排名 18/18**
**两步决策复现海顺(SZ:123183)/莱克(SH:113659)/特纸(SH:111002)，PASS=True**

## 双口径说明（V6 已知设计，勿"修复"）

- **综合口径**（生成 p32 综合列）：D1 12.7340439% / D2 0.6431931% / D3 49.0874804% / D4 7.5377562% / D5 23.2311561% / D6 6.7663703% —— resid 进入多元回归
- **展示口径**（= `results/weights/weights.json`，p31/p33 权重行与 p05 显示值）：D1 12.5804709% / D2 2.2720227% / D3 47.8588418% / D4 7.3731576% / D5 23.1787551% / D6 6.7367519% —— resid 仅作独立诊断
- `compose()` 默认用 weights.json（展示口径）；**复现 p32 综合列须用 `compose(with_weights=综合口径)`**，两套权重均出自 B0 赋权管线，差异为"resid 是否入回归"（老仓库 B4赋权讲解方案.md §54 已记录）

## 已知怪癖（继承自原始管线，保持行为一致，未修复）

`O_MAP` 中 `('中性',5.2)` 排在 `('中性偏负',3.5)` 之前，startswith 匹配使"中性偏负…"开头的券（欧22、乐歌）经营分得 5.2 而非 3.5——新老两套 compose 同此行为，冻结数字含此口径；改动将破坏与 p32 的一致性。
