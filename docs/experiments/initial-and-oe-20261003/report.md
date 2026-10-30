# 最初算法对照与稳定 OE 实验

## 结论

OE 已实现并完成真实数据实验，但目前不接入默认优化流程。同样 24 个候选的数值估计升级在五组已评估数据中取得 2 组改善、3 组退步；扩大到 102 个候选取得 3 组改善、2 组退步。由源 Validation 决定加入 OE 后，五组 Test 中仅换热器改善，锅炉和蒸馏 C 退步，A/B 保持当前候选池结果。不能宣称全面优于最初算法。

## 对照范围与可复现性

- 最初版本取自 Git f832237：原样提取 `_estimate` 和 `_structure_grid` 两个函数，24 个低阶 ARX 候选，原始无截距 OLS / Ridge。不是之前的 60 候选版本。
- 这是模型层消融。两侧统一全部连续 Train 样本、前 40% Train 时滞估计、60/20/20 时间划分、43 点共同历史和安全自由仿真评分；未重放最初版清洗、选段、Optuna 与完整产品流程。
- 每个候选统一训练行 `[43, floor(N*0.6)-43)`、Validation 评分行 `[floor(N*0.6)+43, floor(N*0.8))`。Test 从 `floor(N*0.8)+43` 开始。预测开始前可使用真实历史，预测开始后不更新输出状态。
- 唯一选模目标是最小 Validation 自由仿真 RMSE。所有模型与参数先写入 development.json，生成哈希封印后才评分 Test；未来输出替换为 NaN 时预测逐值不变。
- initial24、affine24、oe24 候选数相等，但计算预算不等。OE 每个候选最多两个非线性求解起点，每起点 max_nfev=100，额外记录包含数值 Jacobian 的实际残差调用次数。current102 另有 102 候选，不能把扩容收益归于数值估计。
- affine24 调用当前 affine OLS/Ridge 估计器；current102 调用当前 ARX/FIR/Huber/TC/past_residual 候选，仍采用本实验统一选模规则。它们不是当前正式产品的完整闭环性能。
- 五组源数据此前已经评估，属于开发回归证据。下方跨运行记录在选择目标、冻结源模型之后首次评分，属于同一试验装置的新运行检查。

## 源数据 Test：自由仿真 RMSE

| 数据 | 最初 24 | affine 24 | 当前 102 | OE 24 | 源 Validation 选用 |
|---|---:|---:|---:|---:|---|
| boiler | 21.646893 | 2.623390 | 1.880787 | 1.883763 | oe24 |
| exchanger | 1.039346 | 1.229356 | 1.163761 | 1.121485 | oe24 |
| distillation_a | 1.835832 | 1.914690 | 1.800150 | 1.824880 | current102 |
| distillation_b | 2.507946 | 5.990018 | 3.254722 | 2.549563 | current102 |
| distillation_c | 1.534429 | 0.842534 | 0.804825 | 0.857703 | oe24 |

误差越低越好；各数据使用各自输出的物理单位，不能直接跨数据集平均。最初 24 → affine 24 的变化：
- boiler：RMSE 下降 87.9%。
- exchanger：RMSE 上升 18.3%。
- distillation_a：RMSE 上升 4.3%。
- distillation_b：RMSE 上升 138.8%。
- distillation_c：RMSE 下降 45.1%。

OE 在蒸馏 B 的 Test 比当前 102 低约 21.7%，但源 Validation 选择的是 current102，正式选择结果不计入这项事后可见收益。当前方法和 OE 在多组数据上的 FIT 仍为负，表示误差超过以该评分区间均值为参照的波动尺度。

## 计算成本：整池 CPU 秒

| 数据 | 最初 24 | affine 24 | 当前 102 | OE 24 |
|---|---:|---:|---:|---:|
| boiler | 0.0283 | 0.0422 | 0.4522 | 1.3117 |
| exchanger | 0.0137 | 0.0190 | 0.1135 | 0.7831 |
| distillation_a | 0.0184 | 0.0279 | 0.3058 | 0.8402 |
| distillation_b | 0.0043 | 0.0069 | 0.0490 | 0.5586 |
| distillation_c | 0.0071 | 0.0110 | 0.0938 | 0.8732 |

单次本机运行，输入输出和延迟提案的公共准备成本未计入各池；不作为稳定的性能基准。完整候选、失败与求解工作量保存在 development.json。

## 尚未评估过的运行：冻结参数跨工况检查

| 来源/角色 | 行数 | 初始 RMSE | 当前 102 RMSE | OE RMSE | 源 Validation 所选 RMSE | 持续值基线 RMSE |
|---|---:|---:|---:|---:|---:|---:|
| distillation_a / anomalous_stress | 3044 | 2.272018 | 1.817771 | 1.762739 | 1.817771 | 1.688380 |
| distillation_b / anomalous_stress | 1068 | — | — | — | 时间重复，未评分 | — |
| distillation_c / anomalous_stress | 557 | 4.973829 | 1.834531 | 3.293635 | 3.293635 | 1.096596 |
| distillation_b / short_normal_boundary | 158 | 0.057566 | 0.059356 | 0.071313 | 0.059356 | 0.077035 |
| distillation_c / short_normal_boundary | 172 | 2.248545 | 4.266522 | 3.841214 | 3.841214 | 1.111757 |

- 3 条异常运行作为压力测试、2 条正常短运行作为边界检查；不是五条同等长度正常泛化测试，也不是不同工厂。
- 蒸馏 B 异常记录存在重复时间戳，保留失败记录并排除评分。未根据其输出误差选择修复方式。
- A/C 异常记录各有一处 60 秒间隔，按原始行序与名义 30 秒模型计算，只能作为含采样缺口的近似压力测试。正常短记录均为严格 30 秒间隔。
- 4 条可计算记录中，源 Validation 所选模型在 3 条上的误差高于持续值基线，跨工况可靠性仍不足。
- 不在目标运行重新拟合参数或选择模型。仅使用前 43 点真实输出初始化，之后输入已知，所有真实未来输出替换为 NaN 后预测不变。

## OE 模块与局限

`backend/algorithms/identifiability/output_error.py` 实现共享分母 MISO OE：Train 自由仿真误差、Train 单独仿射缩放、Schur 反射系数稳定约束、两个固定求解起点、未收敛显式失败。参数转换回物理单位后可由通用自由仿真器重放。

OE24 复用初始网格的 na/nb 和两档正则化字段；在 OE 内 na 表示过程分母 nf，网格中的 ols 字段只标记零正则化档，实际执行的是非线性 OE 求解。OE 正则化针对标准化参数和平均仿真误差，其数值强度不等同于 ARX 最小二乘正则化。

目前仅支持连续完整训练区间，未接入接口、前端、选段优化和自动报告，不把它包装为 ARX。没有声称 OE 残差是一阶 ARX 预测残差。共享分母限制、历史近似初态和局部最优均需要后续检验。定义参考：[MathWorks OE 文档](https://www.mathworks.com/help/ident/ref/oe.html)。

## 下一步优先级

1. 先统一处理重复时间、采样缺口和连续窗口；把原始记录与处理后的索引映射写入报告，避免选段拼接改变动力学。
2. 在新运行上预先冻结工况变化检测与持续值基线门槛，再做验证集验收；不能因为当前 Test 不好就回头改其模型。
3. 比较 10%、25%、50%、100% 数据预算，并按 Train 输入范围、变化率和质量分层选段，使用验证误差决定增加哪一类片段。
4. 工况差异得到证据支持后，再尝试局部模型与基于已知输入/历史的路由。OE 保持实验选项；新增默认策略必须有新留出运行支撑。

## 复现命令

从项目根目录运行，选择全新输出目录（脚本拒绝覆盖协议/结果）：

```sh
INDUSOPT_LLM_PROVIDER=none OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 backend/.venv/bin/python backend/scripts/benchmark_initial_and_oe.py --stage develop --manifest docs/experiments/generalization-20261003/data-manifest.json --out /path/to/new-experiment
INDUSOPT_LLM_PROVIDER=none backend/.venv/bin/python backend/scripts/benchmark_initial_and_oe.py --stage evaluate --manifest docs/experiments/generalization-20261003/data-manifest.json --out /path/to/new-experiment
```

transfer-protocol.json 保留运行选择及源模型封印；transfer-parser-repair.json 记录首次评分前修复日期时间格式的审计。旧实验与旧报告保持原样。

## 验证结果

- 后端完整测试：645 通过、3 项队列测试因默认环境无 Redis 跳过。另启独立临时 Redis 补跑这 3 项，全部通过并清理服务；共 648 项不同测试通过。
- 新增 OE / 原始基线 / 原始时间轴测试共 12 项，覆盖训练前缀隔离、未来输出不变性、单位变换、稳定性、参数恢复、显式失败和两种真实日期时间格式。
- 新增文件 Ruff、git diff --check 和依赖一致性检查均通过。保留现有 Starlette/httpx 弃用提示。
- baseline-reference-repair.json 将最初版本引用固定为 f832237（与最初协议记录的 HEAD 完全相同），避免以后提交改变基线；原始源码哈希、数值代码与模型封印验证通过，已保存的评分没有修改。
