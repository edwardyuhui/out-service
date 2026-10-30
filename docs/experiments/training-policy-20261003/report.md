# 训练数据策略优化与实测验证

## 本轮结论与发布策略

**实验搜索未带来全面改善，当前默认保留 established 搜索。** 五组回归仅两组误差小幅下降，三组上升；paired_coverage 通过接口参数或页面实验开关显式启用。以下表格属于实验模式，不代表默认模式的性能。
默认启用失败回退、验证效果提示和恒定输出指标修复。新搜索的时间覆盖／全量对照用于进一步实验，暂不作为默认能力改善的证据。

## 改动

- 每个 Trial 同时比较全量有效训练行和质量门控后的优选片段，使用相同时滞候选、模型结构网格和滚动验证边界。两种策略各保留短名单。
- 第一项 Trial 固定使用最早 Train 提出的中间时滞候选，与强全量基线保持可比；它计入原有 Trial 预算。
- 选段增加可搜索的三个时间分箱覆盖约束。只从通过质量门控的窗口中选取，遵守唯一行预算；不能把时间覆盖当作物理工况覆盖。
- 选段失败或默认基线不通过数值／效果检查时，仍评估全量训练候选；数据格式或系统错误仍按失败处理。
- 每折检查自由仿真 FIT 是否为正、是否优于固定持值预测。页面和报告提示效果不足；搜索完成与模型效果分开表达。这些是项目内部证据规则，题目没有统一 FIT 达标阈值。
- 恒定或只有浮点舍入级波动的输出，FIT、R²、NRMSE 为无定义，仍保留 MAE／RMSE。

## 实验边界

300 项 Trial，五个预先声明的种子，每组十项；69344 次完成的模型／折拟合。所有模型先冻结，再固定系数回放 Test。
原来五组数据用于回归，不能再作为本次独立泛化证据。新增蒸馏 A 的 op007 正常运行来自同一真实实验装置，检验新工况，不能声称验证了新工厂。三组蒸馏场景也来自同一装置。
训练／验证／测试按时间顺序 60%／20%／20%，共同历史隔离为 43 个样本；滚动验证折有重叠，得分用于开发选择。所有失败和所有种子均保留。

## 固定 Test 回放

| 数据 | 用途 | 数据策略 | 上轮 RMSE | 本轮 RMSE | 本轮 FIT | 验证效果检查 |
|---|---|---|---:|---:|---:|---|
| boiler | regression | selected | 2.2141 | 2.6853 | 28.2471 | passed |
| exchanger | regression | selected | 0.4969 | 0.5031 | 49.9295 | passed |
| distillation_a | regression | selected | 1.9838 | 1.9437 | -12.4393 | insufficient |
| distillation_b | regression | selected | 6.3130 | 6.1433 | -557.8682 | insufficient |
| distillation_c | regression | selected | 0.4496 | 0.5463 | 20.0216 | insufficient |
| distillation_a_new_op007 | new_operating_run | selected | 无定义／无模型 | 0.9912 | 34.6596 | passed |

RMSE 越低越好，FIT 保留原始负值。表中种子按滚动验证选择，未按 Test 排名。变化来自时滞、结构和数据策略共同搜索，不能单独归因于覆盖约束或 D-最优选段。

## 固定系数跨运行迁移

| 目标运行 | 用途 | 原全量基线 RMSE | 当前全量基线 RMSE | 本轮寻优 RMSE | 持值 RMSE | FIT |
|---|---|---:|---:|---:|---:|---:|
| same_operating_point_new_run | regression_transfer | 3.6723 | 3.1227 | 2.7032 | 2.5936 | -45.5945 |
| different_operating_point_new_run | regression_transfer | 0.9645 | 1.1187 | 2.0204 | 0.0000 | 无定义／无模型 |
| different_operating_point_op007 | new_operating_run_transfer | 4.9310 | 5.8834 | 4.0150 | 2.0193 | -163.5306 |

源模型只在 op004 的源验证集上选择；目标运行不重估系数或截距。开头的历史样本只按冻结的初始化策略提供上下文。前两个目标为已知回归，新 op007 为本轮新增迁移检查。

## 可复现与限制

- `protocol.json` 保存参数、种子、代码哈希；`data-manifest.json` 保存来源、物理变量和 CSV 哈希。
- `development.json` 保存全部 Trial、系数、预处理和训练索引；`freeze-seal.json` 封存后 `test-results.json` 才写入 Test 指标，回放时禁止参数估计。
- `post-confirmation-rollout.json` 记录观察结果后的发布决策：实验模式数学计算保持不变，默认切回原搜索；`established-default-verification.json` 比较旧冻结模型，核对系数、截距、行索引和权重。
- `typing-maintenance.json` 单独记录冻结后修改类型注解、叙述器布尔返回类型与无效选段参数过滤的补丁；数值算法未改。
- 时间分箱保障记录的时间分布，不能确认每种真实工况均被覆盖；持值对照通过也不构成 APC 可部署证明。
- 验证选择不能保证所有未知 Test 均改善。需要非线性／工况分区或更多物理可操纵变量的过程，仍可能自由仿真失败。

原始来源：[锅炉工厂实测](https://doi.org/10.6084/m9.figshare.28868849)，[DaISy 换热器实验](https://ftp.esat.kuleuven.be/pub/SISTA/data/process_industry/exchanger.txt)，[TUM 连续蒸馏实测](https://doi.org/10.5281/zenodo.17628963)。

## 最终验证

- 后端完整回归：622 项通过；隔离 Redis／真实 RQ 另补跑的 3 项全部通过，共 625 个不同测试用例。最终报告与大模型回归另外复核 70 项通过。
- 前端：277 项通过，类型检查和构建通过。
- 六组数据的上传、寻优、模型保存、固定参数 Test 评价、逐行严格导出、真实 DeepSeek 报告全部通过。最终结论已明确 Train／Validation／Test 的用途。
- 默认策略复现旧五组冻结模型：系数、截距、训练行、权重一致。原实验材料与本轮封存 Test 结果未改动。
- 后端全项目 mypy 仍有 22 个既有错误；不能声称全部类型检查通过。

所有检查与最终哈希见 `release-validation.json`；修复前报告保留，最终报告链接记录在 `api-integration.json`。
