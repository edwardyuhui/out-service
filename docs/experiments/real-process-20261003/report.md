# 真实过程数据评测

模型仅依据 Validation 选择；固定系数在尾部 Test 上评价。以下是离线辨识结果。

主比较：同一数据、时间分区、每通道时滞及 60 个模型候选，选段方法使用相同的唯一训练行预算上限。全量训练是额外参考。

| 数据/输出 | 训练比例 | 策略 | 训练行 | 验证 FIT | Test FIT | Test RMSE | 耗时/s |
|---|---:|---|---:|---:|---:|---:|---:|
| dryer2/dry_bulb_temperature | 50% | full | 393 | -26.53 | -110.83 | 3.79423 | 0.19 |
| dryer2/dry_bulb_temperature | 50% | random_contiguous | 80 | -22.32 | -152.58 | 4.54564 | 0.17 |
| dryer2/dry_bulb_temperature | 50% | energy | 80 | 18.96 | -45.02 | 2.61000 | 0.16 |
| dryer2/dry_bulb_temperature | 50% | single_dopt | 90 | 27.78 | -87.74 | 3.37870 | 0.18 |
| dryer2/dry_bulb_temperature | 50% | ensemble_dopt | 90 | -7.83 | -114.03 | 3.85195 | 0.19 |
| dryer2/dry_bulb_temperature | 50% | adaptive_ensemble | 92 | 47.77 | -23.94 | 2.23054 | 0.21 |
| dryer2/dry_bulb_temperature | 60% | full | 473 | -12.96 | -101.06 | 3.61849 | 0.22 |
| dryer2/dry_bulb_temperature | 60% | random_contiguous | 100 | -45.24 | -2.53 | 1.84520 | 0.17 |
| dryer2/dry_bulb_temperature | 60% | energy | 100 | -31.58 | -96.98 | 3.54503 | 0.20 |
| dryer2/dry_bulb_temperature | 60% | single_dopt | 110 | -35.38 | -152.15 | 4.53802 | 0.20 |
| dryer2/dry_bulb_temperature | 60% | ensemble_dopt | 110 | -28.11 | -143.81 | 4.38780 | 0.19 |
| dryer2/dry_bulb_temperature | 60% | adaptive_ensemble | 114 | -4.05 | -127.10 | 4.08714 | 0.23 |
| evaporator/product_dry_matter | 50% | full | 3108 | 29.42 | 31.64 | 0.59518 | 1.26 |
| evaporator/product_dry_matter | 50% | random_contiguous | 760 | 21.95 | 23.73 | 0.66401 | 0.98 |
| evaporator/product_dry_matter | 50% | energy | 760 | 25.33 | 15.55 | 0.73520 | 0.92 |
| evaporator/product_dry_matter | 50% | single_dopt | 40 | 7.07 | 34.99 | 0.56595 | 0.84 |
| evaporator/product_dry_matter | 50% | ensemble_dopt | 40 | 22.62 | 40.90 | 0.51456 | 0.84 |
| evaporator/product_dry_matter | 50% | adaptive_ensemble | 135 | 9.21 | 37.01 | 0.54844 | 0.91 |
| evaporator/product_dry_matter | 60% | full | 3743 | 38.41 | 32.33 | 0.58917 | 1.02 |
| evaporator/product_dry_matter | 60% | random_contiguous | 920 | 47.55 | 40.63 | 0.51687 | 0.82 |
| evaporator/product_dry_matter | 60% | energy | 920 | 39.74 | 34.68 | 0.56864 | 0.82 |
| evaporator/product_dry_matter | 60% | single_dopt | 40 | -26.10 | -41.79 | 1.23442 | 0.74 |
| evaporator/product_dry_matter | 60% | ensemble_dopt | — | — | — | NO_DYNAMIC_SEGMENT_FOUND | 0.01 |
| evaporator/product_dry_matter | 60% | adaptive_ensemble | 179 | 27.00 | 27.82 | 0.62841 | 1.05 |
| glassfurnace/temperature_sensor_1 | 50% | full | 587 | 39.04 | 4.57 | 0.80246 | 0.31 |
| glassfurnace/temperature_sensor_1 | 50% | random_contiguous | 120 | 35.06 | -3.85 | 0.87329 | 0.21 |
| glassfurnace/temperature_sensor_1 | 50% | energy | 120 | 30.68 | -7.97 | 0.90790 | 0.21 |
| glassfurnace/temperature_sensor_1 | 50% | single_dopt | 20 | 8.17 | -20.88 | 1.01651 | 0.15 |
| glassfurnace/temperature_sensor_1 | 50% | ensemble_dopt | 20 | -4.58 | -13.21 | 0.95199 | 0.13 |
| glassfurnace/temperature_sensor_1 | 50% | adaptive_ensemble | 139 | 28.33 | -29.44 | 1.08852 | 0.24 |
| glassfurnace/temperature_sensor_1 | 60% | full | 702 | 34.19 | -2.88 | 0.86517 | 0.29 |
| glassfurnace/temperature_sensor_1 | 60% | random_contiguous | 160 | 26.09 | -11.47 | 0.93742 | 0.23 |
| glassfurnace/temperature_sensor_1 | 60% | energy | 160 | 18.35 | -15.74 | 0.97332 | 0.23 |
| glassfurnace/temperature_sensor_1 | 60% | single_dopt | 20 | 0.88 | 1.13 | 0.83140 | 0.13 |
| glassfurnace/temperature_sensor_1 | 60% | ensemble_dopt | 20 | -0.31 | -1.32 | 0.85198 | 0.12 |
| glassfurnace/temperature_sensor_1 | 60% | adaptive_ensemble | 171 | 28.64 | -3.10 | 0.86697 | 0.24 |

## 口径与限制

- FIT 是自由仿真拟合指标，不是准确率；表中 Test FIT 不裁剪负值。
- 每个训练比例在同一条序列上划分；两种比例共享尾部 Test，不是独立工厂或独立重复样本。
- 随机连续片段为预先固定的一次种子运行，不构成统计显著性证明。
- 所有方法保留原时间索引，不把不连续片段拼接后生成滞后。
- 25% 是唯一训练行预算上限，窗口不可拆分，实际使用量可能不同。
- 每通道时滞在训练/验证范围内估计；共享估计耗时单独记录，表内耗时为选段、模型扫描和最终评价。
- 蒸发器和玻璃炉的物理采样周期未注明，CSV 的 1 秒占位不用于物理时滞解释；数值误差沿用源数据尺度。
- 未进行生产控制投运或企业现场验证。

完整配置、数据与算法 SHA256、失败候选统计、选中行和 Test 预测保存在 results.json。
