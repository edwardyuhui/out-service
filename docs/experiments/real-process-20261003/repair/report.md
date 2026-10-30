# 算法修复与验证（2026-10-03）

本轮落实研究路线中的 P0 与 P1：修复诊断误触发和仿真未来依赖，加入高阶正则 ARX、TC 正则 FIR，以及滚动时间验证。真实数据模型对照的误差比中位数为 0.9139；完整寻优中的干燥机首个输出仍有明显泛化问题。

## 已实现

1. 输入—残差诊断改为 Holm 多重检验校正，覆盖全部通道与 0–20 阶时滞；用 Bartlett 方差近似和绝对自相关乘积保守调整有效样本数。少于 30 行或时间索引不连续时返回 inconclusive。保留每个检验的相关系数、有效样本数、原始与校正后的 p 值，反馈只使用拒绝通道。这是平稳序列近似下的关联诊断，不能判断因果或唯一故障原因。
2. 自由仿真移除真实输出幅度限幅。固定数值边界 1e100 只用于检测溢出风险，越界显式标记 SIMULATION_DIVERGED；失败的 FIT/RMSE 返回空值，系数和一步预测诊断保留，寻优拒绝该模型。FIT 保留原始负值。
3. 模型网格保留原有 60 个低阶候选，新增 18 个高阶 Ridge ARX（最高 na/nb=12）和 12 个 TC FIR（8/16/24 阶输入脉冲响应，β=0.8/0.95，α=0.1/10），共 90 个候选。FIR 使用 na=0、逐输入通道的 K(i,j)=β^max(i,j) 核，标准化斜率有正则先验，偏置不受惩罚。复杂度使用有效参数数。
4. 最新 Validation 筛选前 6 个候选，并保留各模型家族的最佳代表；最多 3 个时间折选择最终模型。每折重新拟合训练标准化、质量统计和选段；数据驱动时滞建议仅读取最早一折 Train。最终分数为各折分数均值减去 0.25 倍标准差，语义版本为 v3。
5. 全部候选使用共同历史隔离长度：max(请求 guard, 最大候选历史)。默认搜索最大 nk=20、FIR 长度24，对应 guard=43；最终保存和评价重放这个实际值。
6. 正式寻优诊断页面回放保存的系数、偏置、样本索引、权重和模型家族，禁止重新拟合。旧 artifact 缺失家族时按 ARX 处理，缺失偏置时按0处理。前端建模页支持 FIR、TC衰减参数和更高阶数。明确请求 ARX 的 Agent 结构确认继续使用 ARX 家族；一般寻优可以选择 FIR。

## 真实数据模型对照

三套公开 DaISy 数据的 12 个输出。Train/Validation/Test=60%/20%/20%，共同 guard=43。全部模型使用相同、仅由最早 Train 提出的固定时滞和完整训练行；两组都使用本轮修复后的估计、仿真与单折评分。比较“原60候选＋最新Validation”和“90候选＋滚动Validation”。这项对照同时改变模型网格与验证方式，不能单独归因某个改动。

每个输出先冻结配置，再打开 Test。共尝试1080个最新Validation候选，其中1059个得到可用分数；新方法最终7个输出选中FIR。结果为9个改善、2个持平、1个变差；Test RMSE比中位数0.9139，最差1.0052。

| 数据集 | 输出 | 低阶 Test RMSE | 新模型 Test RMSE | 比值 | 新模型 |
|---|---|---:|---:|---:|---|
| dryer2 | dry_bulb_temperature | 2.7055 | 2.7055 | 1.0000 | ARX na=1, nb=3 |
| dryer2 | wet_bulb_temperature | 0.9053 | 0.6044 | 0.6676 | ARX na=12, nb=4 |
| dryer2 | raw_material_moisture | 1.5135 | 1.5213 | 1.0052 | ARX na=4, nb=2 |
| evaporator | product_dry_matter | 0.8665 | 0.5708 | 0.6587 | TC FIR nb=24 |
| evaporator | product_flow | 0.9956 | 0.8167 | 0.8203 | TC FIR nb=8 |
| evaporator | product_temperature | 0.9722 | 0.7224 | 0.7431 | TC FIR nb=24 |
| glassfurnace | temperature_sensor_1 | 0.7915 | 0.7689 | 0.9714 | ARX na=4, nb=3 |
| glassfurnace | temperature_sensor_2 | 0.8756 | 0.8153 | 0.9312 | TC FIR nb=8 |
| glassfurnace | temperature_sensor_3 | 0.8857 | 0.8208 | 0.9267 | TC FIR nb=8 |
| glassfurnace | temperature_sensor_4 | 0.9825 | 0.9825 | 1.0000 | ARX na=2, nb=2 |
| glassfurnace | temperature_sensor_5 | 0.8175 | 0.7366 | 0.9011 | TC FIR nb=16 |
| glassfurnace | temperature_sensor_6 | 0.9631 | 0.7595 | 0.7885 | TC FIR nb=16 |

这批数据的 Test 已在此前研究中查看，当前结果是回归与开发证据，仍需新设备或新时间段做独立确认。玻璃炉部分输出高度相关，12个输出不能视为12个独立重复实验。dry_bulb_temperature没有改善，raw_material_moisture变差约0.5%。蒸发器和玻璃炉的CSV时间戳不代表已核实的物理采样周期。

## 实际寻优流程

使用真实 run_study 每套数据首个输出各10次试验，30次全部完成；最优模型均通过3个时间折，冻结后再评价Test。包含质量门控、选段、时滞搜索、模型网格与反馈。

| 数据集 | 最优家族 | 最新 Validation FIT | Test FIT | Test RMSE |
|---|---|---:|---:|---:|
| dryer2 | ARX | -15.56% | -92.99% | 3.0233 |
| evaporator | FIR | 46.95% | 46.93% | 0.4638 |
| glassfurnace | ARX | 33.34% | 29.58% | 0.5987 |

干燥机当前 Test FIT=-92.99%，说明完整流程仍不足以处理这个输出的变化；滚动验证与增加阶数并没有自动解决偏移和激励覆盖。下一步应研究工况覆盖、动态与基线偏移的区分，以及预测方差驱动的选段。此次没有按Test结果调整模型。旧版完整寻优使用guard32，不能把其FIT与本表直接当成严格前后对照。

## 诊断误触发校准

每种情况500次、每次200行、3个独立输入通道，种子20261003。同一组样本同时评价旧、新规则。

| 独立序列的内部自相关 | 旧规则误触发 | 新规则误触发 |
|---|---:|---:|
| AR(1) φ=0.0 | 477/500 (95.4%) | 6/500 (1.2%) |
| AR(1) φ=0.8 | 500/500 (100.0%) | 2/500 (0.4%) |

这是固定种子下的有限样本校准。Bartlett校正仍依赖平稳近似；较低误触发率不等于真实工业工况下的严格显著性保证。

## 文件与复现

- `model-ablation.json`：全部输出对照、配置、数据哈希、折指标及噪声校准。
- `optimizer-results.json`：30个真实寻优试验及每折证据。
- `fir-api-smoke.json`：三套数据的上传、配置、时滞补偿、选段、FIR保存、固定系数评价与CSV导出；全部成功，评价禁止调用参数估计，artifact哈希保持不变。
- `validation.json`：最终检查与历史失败的对比。

在backend目录运行：

```sh
OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 .venv/bin/python scripts/benchmark_repaired_models.py --data-dir ../../公开工业数据集/DaISy --out ../docs/experiments/real-process-20261003/repair/model-ablation.json
OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 .venv/bin/python scripts/benchmark_real_optimization.py --data-dir ../../公开工业数据集/DaISy --out ../docs/experiments/real-process-20261003/repair/optimizer-results.json --trials 10
OPENBLAS_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 .venv/bin/python scripts/smoke_real_process_api.py --data-dir ../../公开工业数据集/DaISy --benchmark ../docs/experiments/real-process-20261003/final/results.json --out ../docs/experiments/real-process-20261003/repair/fir-api-smoke.json --family FIR
```

TC核依据：[Chen、Ohlsson与Ljung（2012）](https://www.diva-portal.org/smash/get/diva2:556599/FULLTEXT01.pdf)。

## 最终检查

后端全量578通过、23失败、3跳过；失败项集合与改动前完全一致，无新增失败。207项算法、建模、寻优与选段相关测试均在全量运行中通过。前端相关45项测试、vue-tsc、构建通过；变更范围Ruff与git diff --check通过。全局mypy仍有22个历史错误，按文件与错误内容对比一致，无新增类型错误。
