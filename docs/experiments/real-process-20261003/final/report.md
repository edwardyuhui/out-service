# 真实过程数据评测

模型仅依据 Validation 选择；固定系数在尾部 Test 上评价。以下是离线辨识结果。

主比较：同一数据、时间分区、每通道时滞及 60 个模型候选，选段方法使用相同的唯一训练行预算上限。全量训练是额外参考。

| 数据/输出 | 训练比例 | 策略 | 训练行 | 验证 FIT | Test FIT | Test RMSE | 耗时/s |
|---|---:|---|---:|---:|---:|---:|---:|
| dryer2/dry_bulb_temperature | 50% | full | 393 | -27.53 | -113.56 | 3.84340 | 0.23 |
| dryer2/dry_bulb_temperature | 50% | random_contiguous | 80 | -21.91 | -154.00 | 4.57117 | 0.21 |
| dryer2/dry_bulb_temperature | 50% | energy | 80 | -23.80 | -93.37 | 3.48014 | 0.19 |
| dryer2/dry_bulb_temperature | 50% | single_dopt | 90 | 7.88 | -155.77 | 4.60314 | 0.20 |
| dryer2/dry_bulb_temperature | 50% | ensemble_dopt | 90 | -100.00 | -178.91 | 5.01955 | 0.21 |
| dryer2/dry_bulb_temperature | 50% | adaptive_ensemble | 92 | 48.78 | -69.18 | 3.04466 | 0.23 |
| dryer2/dry_bulb_temperature | 60% | full | 479 | -15.92 | -106.15 | 3.71011 | 0.23 |
| dryer2/dry_bulb_temperature | 60% | random_contiguous | 100 | -2.81 | 35.45 | 1.16176 | 0.17 |
| dryer2/dry_bulb_temperature | 60% | energy | 100 | 9.79 | -58.65 | 2.85524 | 0.20 |
| dryer2/dry_bulb_temperature | 60% | single_dopt | 110 | -27.76 | -128.91 | 4.11961 | 0.20 |
| dryer2/dry_bulb_temperature | 60% | ensemble_dopt | 110 | 26.67 | -148.86 | 4.47864 | 0.21 |
| dryer2/dry_bulb_temperature | 60% | adaptive_ensemble | 114 | 53.50 | -102.27 | 3.64022 | 0.24 |
| dryer2/wet_bulb_temperature | 50% | full | 381 | 5.73 | -73.90 | 0.93884 | 0.25 |
| dryer2/wet_bulb_temperature | 50% | random_contiguous | 80 | 40.49 | -37.02 | 0.73971 | 0.20 |
| dryer2/wet_bulb_temperature | 50% | energy | 80 | 2.78 | -71.06 | 0.92349 | 0.20 |
| dryer2/wet_bulb_temperature | 50% | single_dopt | 90 | -66.69 | -129.35 | 1.23821 | 0.22 |
| dryer2/wet_bulb_temperature | 50% | ensemble_dopt | 90 | -54.48 | -109.19 | 1.12936 | 0.21 |
| dryer2/wet_bulb_temperature | 50% | adaptive_ensemble | 92 | 64.90 | -20.67 | 0.65147 | 0.23 |
| dryer2/wet_bulb_temperature | 60% | full | 483 | 7.13 | -60.21 | 0.86492 | 0.21 |
| dryer2/wet_bulb_temperature | 60% | random_contiguous | 100 | -18.75 | -77.62 | 0.95894 | 0.17 |
| dryer2/wet_bulb_temperature | 60% | energy | 100 | 64.36 | -15.08 | 0.62129 | 0.17 |
| dryer2/wet_bulb_temperature | 60% | single_dopt | 110 | 52.50 | 22.18 | 0.42012 | 0.18 |
| dryer2/wet_bulb_temperature | 60% | ensemble_dopt | 110 | 52.06 | 24.10 | 0.40975 | 0.19 |
| dryer2/wet_bulb_temperature | 60% | adaptive_ensemble | 114 | 56.23 | 6.70 | 0.50369 | 0.23 |
| dryer2/raw_material_moisture | 50% | full | 384 | -100.00 | -181.84 | 1.80802 | 0.22 |
| dryer2/raw_material_moisture | 50% | random_contiguous | 80 | -100.00 | -195.47 | 1.89546 | 0.17 |
| dryer2/raw_material_moisture | 50% | energy | 80 | -20.24 | -69.77 | 1.08909 | 0.18 |
| dryer2/raw_material_moisture | 50% | single_dopt | 90 | -19.57 | -62.96 | 1.04539 | 0.18 |
| dryer2/raw_material_moisture | 50% | ensemble_dopt | 90 | -39.32 | -114.06 | 1.37322 | 0.21 |
| dryer2/raw_material_moisture | 50% | adaptive_ensemble | 92 | -45.84 | -129.33 | 1.47115 | 0.22 |
| dryer2/raw_material_moisture | 60% | full | 467 | -38.03 | -111.10 | 1.35421 | 0.23 |
| dryer2/raw_material_moisture | 60% | random_contiguous | 100 | -66.42 | -154.15 | 1.63038 | 0.16 |
| dryer2/raw_material_moisture | 60% | energy | 100 | 4.24 | -32.21 | 0.84812 | 0.18 |
| dryer2/raw_material_moisture | 60% | single_dopt | 110 | -100.00 | -230.69 | 2.12136 | 0.19 |
| dryer2/raw_material_moisture | 60% | ensemble_dopt | 110 | -100.00 | -231.79 | 2.12844 | 0.20 |
| dryer2/raw_material_moisture | 60% | adaptive_ensemble | 114 | -58.81 | -170.89 | 1.73778 | 0.24 |
| evaporator/product_dry_matter | 50% | full | 3108 | 29.42 | 31.64 | 0.59518 | 1.14 |
| evaporator/product_dry_matter | 50% | random_contiguous | 760 | 21.95 | 23.73 | 0.66401 | 0.89 |
| evaporator/product_dry_matter | 50% | energy | 760 | 25.33 | 15.55 | 0.73520 | 0.89 |
| evaporator/product_dry_matter | 50% | single_dopt | 760 | 23.08 | 37.67 | 0.54267 | 0.93 |
| evaporator/product_dry_matter | 50% | ensemble_dopt | 760 | 30.59 | 37.42 | 0.54482 | 0.98 |
| evaporator/product_dry_matter | 50% | adaptive_ensemble | 772 | 33.04 | 27.08 | 0.63482 | 1.29 |
| evaporator/product_dry_matter | 60% | full | 3743 | 38.41 | 32.33 | 0.58917 | 1.11 |
| evaporator/product_dry_matter | 60% | random_contiguous | 920 | 47.55 | 40.63 | 0.51687 | 0.86 |
| evaporator/product_dry_matter | 60% | energy | 920 | 39.74 | 34.68 | 0.56864 | 0.86 |
| evaporator/product_dry_matter | 60% | single_dopt | 920 | 51.07 | 40.50 | 0.51799 | 0.90 |
| evaporator/product_dry_matter | 60% | ensemble_dopt | 920 | 49.09 | 41.72 | 0.50735 | 0.99 |
| evaporator/product_dry_matter | 60% | adaptive_ensemble | 929 | 48.57 | 37.78 | 0.54168 | 1.46 |
| evaporator/product_flow | 50% | full | 3116 | 38.46 | 42.44 | 0.57975 | 0.93 |
| evaporator/product_flow | 50% | random_contiguous | 760 | 36.94 | 40.70 | 0.59720 | 0.77 |
| evaporator/product_flow | 50% | energy | 760 | 37.81 | 40.78 | 0.59644 | 0.77 |
| evaporator/product_flow | 50% | single_dopt | 760 | 36.09 | 41.90 | 0.58512 | 0.82 |
| evaporator/product_flow | 50% | ensemble_dopt | 760 | 37.06 | 42.45 | 0.57956 | 0.86 |
| evaporator/product_flow | 50% | adaptive_ensemble | 772 | 37.51 | 42.25 | 0.58164 | 1.16 |
| evaporator/product_flow | 60% | full | 3747 | 36.56 | 40.92 | 0.59500 | 0.94 |
| evaporator/product_flow | 60% | random_contiguous | 920 | 36.71 | 40.95 | 0.59468 | 0.75 |
| evaporator/product_flow | 60% | energy | 920 | 36.64 | 40.28 | 0.60145 | 0.74 |
| evaporator/product_flow | 60% | single_dopt | 920 | 36.15 | 42.62 | 0.57788 | 0.82 |
| evaporator/product_flow | 60% | ensemble_dopt | 920 | 36.85 | 42.77 | 0.57639 | 0.87 |
| evaporator/product_flow | 60% | adaptive_ensemble | 929 | 36.51 | 42.79 | 0.57615 | 1.37 |
| evaporator/product_temperature | 50% | full | 3102 | -1.11 | -4.40 | 0.90050 | 1.09 |
| evaporator/product_temperature | 50% | random_contiguous | 760 | -4.50 | -0.14 | 0.86375 | 0.78 |
| evaporator/product_temperature | 50% | energy | 760 | -2.84 | 4.44 | 0.82424 | 0.81 |
| evaporator/product_temperature | 50% | single_dopt | 760 | 8.93 | 0.41 | 0.85903 | 0.85 |
| evaporator/product_temperature | 50% | ensemble_dopt | 760 | 4.94 | 10.50 | 0.77197 | 0.90 |
| evaporator/product_temperature | 50% | adaptive_ensemble | 772 | 8.90 | 13.29 | 0.74794 | 1.22 |
| evaporator/product_temperature | 60% | full | 3733 | 38.12 | 16.81 | 0.71752 | 1.14 |
| evaporator/product_temperature | 60% | random_contiguous | 920 | 30.59 | 29.32 | 0.60968 | 0.78 |
| evaporator/product_temperature | 60% | energy | 920 | 37.72 | 29.15 | 0.61110 | 0.80 |
| evaporator/product_temperature | 60% | single_dopt | 920 | 38.81 | 20.21 | 0.68821 | 0.85 |
| evaporator/product_temperature | 60% | ensemble_dopt | 920 | 37.76 | 20.79 | 0.68322 | 0.91 |
| evaporator/product_temperature | 60% | adaptive_ensemble | 929 | 39.93 | 19.07 | 0.69803 | 1.30 |
| glassfurnace/temperature_sensor_1 | 50% | full | 587 | 39.04 | 4.57 | 0.80246 | 0.22 |
| glassfurnace/temperature_sensor_1 | 50% | random_contiguous | 120 | 35.06 | -3.85 | 0.87329 | 0.20 |
| glassfurnace/temperature_sensor_1 | 50% | energy | 120 | 30.68 | -7.97 | 0.90790 | 0.20 |
| glassfurnace/temperature_sensor_1 | 50% | single_dopt | 130 | 34.73 | -3.69 | 0.87196 | 0.20 |
| glassfurnace/temperature_sensor_1 | 50% | ensemble_dopt | 130 | 39.60 | -10.74 | 0.93124 | 0.23 |
| glassfurnace/temperature_sensor_1 | 50% | adaptive_ensemble | 139 | 38.16 | 3.14 | 0.81452 | 0.25 |
| glassfurnace/temperature_sensor_1 | 60% | full | 702 | 34.19 | -2.88 | 0.86517 | 0.27 |
| glassfurnace/temperature_sensor_1 | 60% | random_contiguous | 160 | 26.09 | -11.47 | 0.93742 | 0.21 |
| glassfurnace/temperature_sensor_1 | 60% | energy | 160 | 18.35 | -15.74 | 0.97332 | 0.20 |
| glassfurnace/temperature_sensor_1 | 60% | single_dopt | 170 | 15.26 | -37.91 | 1.15969 | 0.22 |
| glassfurnace/temperature_sensor_1 | 60% | ensemble_dopt | 170 | 31.12 | -11.33 | 0.93623 | 0.23 |
| glassfurnace/temperature_sensor_1 | 60% | adaptive_ensemble | 171 | 22.85 | -23.60 | 1.03941 | 0.27 |
| glassfurnace/temperature_sensor_2 | 50% | full | 583 | 36.81 | 11.46 | 0.76104 | 0.24 |
| glassfurnace/temperature_sensor_2 | 50% | random_contiguous | 120 | 18.34 | -1.94 | 0.87624 | 0.20 |
| glassfurnace/temperature_sensor_2 | 50% | energy | 120 | 22.37 | 3.07 | 0.83312 | 0.19 |
| glassfurnace/temperature_sensor_2 | 50% | single_dopt | 130 | 21.19 | -1.70 | 0.87411 | 0.21 |
| glassfurnace/temperature_sensor_2 | 50% | ensemble_dopt | 130 | 18.61 | -3.95 | 0.89349 | 0.23 |
| glassfurnace/temperature_sensor_2 | 50% | adaptive_ensemble | 139 | 1.16 | -32.10 | 1.13550 | 0.28 |
| glassfurnace/temperature_sensor_2 | 60% | full | 703 | 33.00 | 11.82 | 0.75795 | 0.26 |
| glassfurnace/temperature_sensor_2 | 60% | random_contiguous | 160 | 32.18 | 9.92 | 0.77428 | 0.20 |
| glassfurnace/temperature_sensor_2 | 60% | energy | 160 | 34.54 | 13.07 | 0.74717 | 0.20 |
| glassfurnace/temperature_sensor_2 | 60% | single_dopt | 170 | 39.76 | 15.72 | 0.72445 | 0.22 |
| glassfurnace/temperature_sensor_2 | 60% | ensemble_dopt | 170 | 35.06 | 15.51 | 0.72621 | 0.23 |
| glassfurnace/temperature_sensor_2 | 60% | adaptive_ensemble | 171 | -2.44 | -29.80 | 1.11565 | 0.27 |
| glassfurnace/temperature_sensor_3 | 50% | full | 583 | 37.04 | 11.85 | 0.76170 | 0.23 |
| glassfurnace/temperature_sensor_3 | 50% | random_contiguous | 120 | 18.06 | -2.85 | 0.88876 | 0.20 |
| glassfurnace/temperature_sensor_3 | 50% | energy | 120 | 24.84 | 7.41 | 0.80009 | 0.20 |
| glassfurnace/temperature_sensor_3 | 50% | single_dopt | 130 | 21.62 | -1.83 | 0.87993 | 0.21 |
| glassfurnace/temperature_sensor_3 | 50% | ensemble_dopt | 130 | 18.82 | -4.58 | 0.90372 | 0.21 |
| glassfurnace/temperature_sensor_3 | 50% | adaptive_ensemble | 139 | 0.98 | -32.98 | 1.14916 | 0.26 |
| glassfurnace/temperature_sensor_3 | 60% | full | 703 | 32.97 | 11.88 | 0.76148 | 0.26 |
| glassfurnace/temperature_sensor_3 | 60% | random_contiguous | 160 | 31.74 | 9.70 | 0.78033 | 0.21 |
| glassfurnace/temperature_sensor_3 | 60% | energy | 160 | 34.69 | 13.41 | 0.74823 | 0.21 |
| glassfurnace/temperature_sensor_3 | 60% | single_dopt | 170 | 41.04 | 14.81 | 0.73615 | 0.22 |
| glassfurnace/temperature_sensor_3 | 60% | ensemble_dopt | 170 | 41.79 | 17.06 | 0.71670 | 0.23 |
| glassfurnace/temperature_sensor_3 | 60% | adaptive_ensemble | 171 | -2.97 | -30.58 | 1.12838 | 0.28 |
| glassfurnace/temperature_sensor_4 | 50% | full | 587 | 68.28 | 64.68 | 0.36934 | 0.23 |
| glassfurnace/temperature_sensor_4 | 50% | random_contiguous | 120 | 62.03 | 59.40 | 0.42449 | 0.20 |
| glassfurnace/temperature_sensor_4 | 50% | energy | 120 | 64.21 | 61.90 | 0.39834 | 0.20 |
| glassfurnace/temperature_sensor_4 | 50% | single_dopt | 130 | 62.22 | 54.07 | 0.48026 | 0.21 |
| glassfurnace/temperature_sensor_4 | 50% | ensemble_dopt | 130 | 65.48 | 58.54 | 0.43347 | 0.22 |
| glassfurnace/temperature_sensor_4 | 50% | adaptive_ensemble | 139 | 66.99 | 60.10 | 0.41724 | 0.25 |
| glassfurnace/temperature_sensor_4 | 60% | full | 712 | 70.68 | 61.62 | 0.40127 | 0.24 |
| glassfurnace/temperature_sensor_4 | 60% | random_contiguous | 160 | 71.54 | 62.56 | 0.39149 | 0.20 |
| glassfurnace/temperature_sensor_4 | 60% | energy | 160 | 65.71 | 63.09 | 0.38598 | 0.20 |
| glassfurnace/temperature_sensor_4 | 60% | single_dopt | 170 | 55.34 | 57.31 | 0.44641 | 0.20 |
| glassfurnace/temperature_sensor_4 | 60% | ensemble_dopt | 170 | 63.39 | 59.28 | 0.42580 | 0.22 |
| glassfurnace/temperature_sensor_4 | 60% | adaptive_ensemble | 171 | 68.65 | 58.61 | 0.43274 | 0.27 |
| glassfurnace/temperature_sensor_5 | 50% | full | 586 | 48.08 | 56.06 | 0.36363 | 0.23 |
| glassfurnace/temperature_sensor_5 | 50% | random_contiguous | 120 | 35.03 | 33.36 | 0.55142 | 0.20 |
| glassfurnace/temperature_sensor_5 | 50% | energy | 120 | 43.72 | 50.49 | 0.40967 | 0.21 |
| glassfurnace/temperature_sensor_5 | 50% | single_dopt | 130 | 50.91 | 59.50 | 0.33513 | 0.21 |
| glassfurnace/temperature_sensor_5 | 50% | ensemble_dopt | 130 | 45.28 | 44.13 | 0.46234 | 0.23 |
| glassfurnace/temperature_sensor_5 | 50% | adaptive_ensemble | 139 | 48.41 | 51.22 | 0.40365 | 0.26 |
| glassfurnace/temperature_sensor_5 | 60% | full | 711 | 42.05 | 40.41 | 0.49313 | 0.23 |
| glassfurnace/temperature_sensor_5 | 60% | random_contiguous | 160 | 45.43 | 49.66 | 0.41656 | 0.20 |
| glassfurnace/temperature_sensor_5 | 60% | energy | 160 | 30.65 | 25.30 | 0.61815 | 0.20 |
| glassfurnace/temperature_sensor_5 | 60% | single_dopt | 170 | 45.47 | 50.76 | 0.40749 | 0.21 |
| glassfurnace/temperature_sensor_5 | 60% | ensemble_dopt | 170 | 32.75 | 23.76 | 0.63085 | 0.22 |
| glassfurnace/temperature_sensor_5 | 60% | adaptive_ensemble | 171 | 48.69 | 42.82 | 0.47316 | 0.27 |
| glassfurnace/temperature_sensor_6 | 50% | full | 586 | 49.00 | 32.32 | 0.69107 | 0.23 |
| glassfurnace/temperature_sensor_6 | 50% | random_contiguous | 120 | 51.73 | 32.09 | 0.69340 | 0.20 |
| glassfurnace/temperature_sensor_6 | 50% | energy | 120 | 42.58 | 32.64 | 0.68781 | 0.20 |
| glassfurnace/temperature_sensor_6 | 50% | single_dopt | 130 | 53.24 | 25.28 | 0.76295 | 0.21 |
| glassfurnace/temperature_sensor_6 | 50% | ensemble_dopt | 130 | 50.33 | 23.07 | 0.78555 | 0.22 |
| glassfurnace/temperature_sensor_6 | 50% | adaptive_ensemble | 139 | 50.14 | 20.62 | 0.81057 | 0.25 |
| glassfurnace/temperature_sensor_6 | 60% | full | 711 | 48.17 | 31.19 | 0.70258 | 0.23 |
| glassfurnace/temperature_sensor_6 | 60% | random_contiguous | 160 | 52.41 | 32.17 | 0.69261 | 0.19 |
| glassfurnace/temperature_sensor_6 | 60% | energy | 160 | 46.69 | 29.48 | 0.72011 | 0.20 |
| glassfurnace/temperature_sensor_6 | 60% | single_dopt | 170 | 39.65 | 18.07 | 0.83662 | 0.21 |
| glassfurnace/temperature_sensor_6 | 60% | ensemble_dopt | 170 | 33.53 | 17.50 | 0.84237 | 0.23 |
| glassfurnace/temperature_sensor_6 | 60% | adaptive_ensemble | 171 | 45.09 | 22.80 | 0.78831 | 0.27 |

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
