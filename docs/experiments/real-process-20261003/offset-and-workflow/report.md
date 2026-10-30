# 输出偏移初始化与流程修复：实现和实测

2026-10-03。干燥机首个输出的实际寻优 Test RMSE 从 3.0233 降到 1.3103，降低 56.7%；Test FIT 从 −92.99% 提高到 16.36%。蒸发器、玻璃炉首个输出的最优参数及 Test 指标保持不变。干燥机仍有明显的长期预测误差和跨时间段波动。

## 1. 本轮算法修改

在正则 FIR 中增加可选的预测初始输出扰动：先用固定的训练系数计算预测起点之前的残差，再取最近32个样本中的有限残差中位数，作为整段自由仿真的固定偏移。至少需要8个有效样本；历史不足时偏移为0，证据记录 insufficient_history。

- 系数、训练偏置和标准化参数都由 Train 拟合；初始偏移是预测状态估计，不改变模型参数。
- 自由仿真在预测开始后不读取真实输出，也不更新偏移。一步预测使用各时刻之前的残差更新偏移，必须与自由仿真分开解释。
- 原有90个候选保留，新增12个带初始偏移的TC FIR，合计102个。仍由滚动 Validation 选择是否启用。目标语义版本改为v4，阶段缓存工具版本改为4.0.0。
- 保存初始化策略、历史窗口和验证时的取样范围、有效样本数、偏移值。保存模型的重放遵循同一策略；旧模型默认 fixed。手动建模页面可以选择策略，模型卡片显示自由仿真期间偏移固定；图中明确区分全序列连续仿真与分区评分的初始化，横轴使用样本索引。
- 验证结果增加预测起点最后一次观测保持不变的基线及相对技能分数。

思想参考是将过程动态与输出扰动区分处理：[Pannocchia 与 Rawlings（2003）原始论文](https://aiche.onlinelibrary.wiley.com/doi/10.1002/aic.690490213)。本次只实现简单的初始常数扰动估计，没有实现完整的MPC扰动观测器或其理论保证。

## 2. 真实数据：完整寻优

DaISy 的 dryer2、evaporator、glassfurnace；各取首个输出，种子42，每套10次寻优。两轮均使用相同的60%/20%/20%划分和实际guard43、同一选段流程、同一滚动评分。30次试验全部完成；每个胜出配置均经过3个时间折。

| 数据集 | 上轮 Test RMSE | 本轮 Test RMSE | 上轮 Test FIT | 本轮 Test FIT | 本轮策略 |
|---|---:|---:|---:|---:|---|
| dryer2 | 3.0233 | 1.3103 | -92.99% | 16.36% | FIR＋初始偏移 |
| evaporator | 0.4638 | 0.4638 | 46.93% | 46.93% | 固定基线 |
| glassfurnace | 0.5987 | 0.5987 | 29.58% | 29.58% | 固定基线 |

干燥机的最新 Validation FIT 从 −15.56% 提高到50.30%，但此前两个滚动窗口的FIT为5.31%和−46.19%，并未在所有时间段达到可靠精度。完整流程选择的干燥机模型为24阶TC FIR，β=0.8、α=10，带32样本初始偏移。

为检查改善是否仅来自简单保持输出，冻结获选模型后，在同一 Test 预测区间比较两个常数基线：

| 数据集 | 模型 RMSE | 最后观测保持 RMSE | 预测前32点中位数保持 RMSE |
|---|---:|---:|---:|
| dryer2 | 1.3103 | 3.9664 | 3.8837 |
| evaporator | 0.4638 | 0.9578 | 1.1561 |
| glassfurnace | 0.5987 | 1.3704 | 1.1686 |

干燥机相对两个常数基线的RMSE降低约67%和66%。这些基线仅用于冻结模型后的报告，没有用于按Test挑选参数。

## 3. 真实数据：模型网格对照

完整训练行、仅由最早Train估计的共用固定时滞、guard43；排除选段差异。对比上轮90候选＋滚动验证与本轮102候选＋滚动验证：干燥机3个输出改善，其余9个输出保持一致，没有新增退步。

| 数据集/输出 | 上轮90候选 RMSE | 本轮102候选 RMSE | 本轮/上轮 |
|---|---:|---:|---:|
| dryer2/dry_bulb_temperature | 2.7055 | 1.2736 | 0.4707 |
| dryer2/wet_bulb_temperature | 0.6044 | 0.5938 | 0.9825 |
| dryer2/raw_material_moisture | 1.5213 | 0.7331 | 0.4819 |
| evaporator/product_dry_matter | 0.5708 | 0.5708 | 1.0000 |
| evaporator/product_flow | 0.8167 | 0.8167 | 1.0000 |
| evaporator/product_temperature | 0.7224 | 0.7224 | 1.0000 |
| glassfurnace/temperature_sensor_1 | 0.7689 | 0.7689 | 1.0000 |
| glassfurnace/temperature_sensor_2 | 0.8153 | 0.8153 | 1.0000 |
| glassfurnace/temperature_sensor_3 | 0.8208 | 0.8208 | 1.0000 |
| glassfurnace/temperature_sensor_4 | 0.9825 | 0.9825 | 1.0000 |
| glassfurnace/temperature_sensor_5 | 0.7366 | 0.7366 | 1.0000 |
| glassfurnace/temperature_sensor_6 | 0.7595 | 0.7595 | 1.0000 |

若与原60个低阶候选＋最新Validation对比，则12个输出中11个改善、1个持平，RMSE比中位数为0.8044。这包含上一轮模型扩展和验证方式的效果，不能全部归因于本轮初始偏移。

### 预测起点与独立性边界

预测区间从分区边界加guard43开始。初始偏移只读取实际预测起点前32个样本，这些样本可以位于被排除评分的分区暖启动区间；ARX也使用起点前的实测输出作为初始状态。因此这里评价的是有历史观测的预测任务。预测区间内的真实输出只用于计算误差。改变预测起点及其之后的真实输出不改变已有自由仿真预测，已用性质测试检查。

这批数据的Test在此前研究中已经检查过。本轮是开发与回归证据，不能当作独立泛化确认。玻璃炉若干输出高度相关，12个输出不是12次独立工业实验；蒸发器和玻璃炉CSV中的时间戳也不能视为已核实的物理采样周期。

## 4. 流程修复与测试合同更新

实际服务修改：

1. 已成功或失败的模型评价再次触发，返回原持久化结果；避免重新评价或报状态冲突。
2. 已确认、已结束的导出或通用确认再次提交，返回原结果。拒绝后的流程仍不能被批准。
3. 变量确认支持保留全部输入。记录 feature_selection_noop、最终选择和来源版本；不新建CSV版本，不调用正式删除工具，继续建模。保留未知变量、重复删除、删除时间/输出列、删除全部输入等硬约束。

此前23个后端测试失败并不对应23个实际服务故障。测试更新包括：按当前确认后自动推进的生命周期验证；在评价开始前注入损坏来源或缺失模型ID；分别观察直接工具和正式适配器调用；合法的非零时滞fixture；端到端请求明确执行清洗和时滞Apply，并给报告绑定数据版本；规范系统类型 MISO_ARX；删除测试中的未定义变量。针对独立适配器的负面测试暂停后续控制器，再注入错误；完整正面API测试继续验证真实自动推进。没有删除或跳过这些失败测试。前端的一项排版测试改为检查当前参数使用Sans、原始JSON使用Mono的界面合同。

新增及加强的验证包括：预测不读取未来输出、一步预测仅使用过去输出、初始化不改系数与训练偏置、已完成评价重复触发只产生一次记录、成功和失败导出的重复确认、保留全部变量的版本不可变与冲突重放。

## 5. 最终检查

- 后端全量：604通过、0失败、3跳过；三个真实RQ测试用独立临时Redis补测，3个全部通过。合计607个测试均得到通过结果，Redis测试后已关闭。
- 补充重放与保留全部变量检查：19通过。
- 前端全量：273通过；vue-tsc和生产构建通过。
- 变更范围Ruff、git diff --check通过。
- 全局mypy仍有22条已有错误；按文件、错误内容和重复次数与原基线比较一致，无新增错误。
- 三套真实数据的API集成：上传→配置→时滞Apply→选段→带偏移FIR保存→固定参数Test评价→CSV导出全部通过。参数估计调用被禁止，保存artifact哈希不变，预测与手算公式一致。该固定手动配置用于检查集成，部分Test FIT为负，不能替代寻优结果。

## 6. 复现与后续重点

结果文件：model-ablation.json、optimizer-results.json、fir-api-smoke.json、validation.json。上一轮结果保留在相邻repair目录。backend目录运行：

```sh
OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 .venv/bin/python scripts/benchmark_repaired_models.py --data-dir '../../公开工业数据集/DaISy' --out ../docs/experiments/real-process-20261003/offset-and-workflow/model-ablation.json
OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 .venv/bin/python scripts/benchmark_real_optimization.py --data-dir '../../公开工业数据集/DaISy' --out ../docs/experiments/real-process-20261003/offset-and-workflow/optimizer-results.json --trials 10
OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 .venv/bin/python scripts/smoke_real_process_api.py --data-dir '../../公开工业数据集/DaISy' --benchmark ../docs/experiments/real-process-20261003/results.json --out ../docs/experiments/real-process-20261003/offset-and-workflow/fir-api-smoke.json --family FIR --initialization-policy past_residual
```

后续优先检查各验证时段的工况和激励覆盖，为预测给出适当的不确定性估计，并在新设备或未检查的新时间段上确认。若固定偏移仍不足，再用同一数据合同对照带扰动状态的状态空间模型或OE模型。当前16%的干燥机Test FIT不足以支持高精度工业控制的结论。
