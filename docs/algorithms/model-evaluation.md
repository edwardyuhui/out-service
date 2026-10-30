# ProcessPilot 模型评价口径

## 目标

本规范定义闭环寻优的正式比较口径，避免将 Optuna 的首个随机 trial 误称为“优化前基线”，并防止测试集泄漏进寻优过程。

## 时间顺序切分

同一 DatasetVersion 的时序数据按原始时间顺序连续切分：

```text
0 ───────── Train ───────── Validation ───────── Test ───────── N
              60%               20%                20%
```

- Train：ARX 参数拟合，动态区段门控与 D-最优选段也只读取这一段；
- Validation：计算 free-run FIT，作为 Optuna 的唯一选择依据；
- Test：在 best trial 已固定后，只执行一次最终评价。

比例由 `OptimizationStartRequest.train_ratio` 和 `validation_ratio` 记录；余量为 Test。任何 `train_ratio + validation_ratio >= 1` 的请求均被拒绝。系统不随机打乱时序样本。

## 正式 Baseline

每次 Study 在 Optuna 前执行一次确定性的工程默认流程，配置唯一来源为 `app/services/evaluation_policy.py` 的 `DEFAULT_BASELINE_CONFIG`：

| 参数 | 默认值 |
| --- | --- |
| window_size / max_segments | 60 / 10 |
| max_missing_ratio / max_anomaly_ratio | 0.20 / 0.10 |
| min_input_activity_ratio | 0.05 |
| 选段 ARX 结构 na / nb / nk | 2 / 2 / 0 |
| 辨识 ARX 结构 na / nb / nk | 2 / 2 / 0 |
| estimator | OLS |
| train / validation / test | 0.60 / 0.20 / 0.20 |

Baseline 同样执行质量门控、D-最优选段和 ARX，不调用 Optuna。它的参数、validation/test 指标、开始/结束时间、耗时、错误码与 `ProcessingRun` ID 保存于 `optimization_studies.statistics.evaluations.baseline`，并以 `optimization.baseline` 写入 `processing_runs`。

## 寻优与独立 Test

1. 每个 Optuna trial 仅评估 Train 与 Validation，`evaluate_test=false`，不生成 Test 指标、曲线或残差；
2. objective 为稳定模型的 validation free-run FIT 及既有工程惩罚项；Test 从不参与 objective、trial 排名、search space 调整或 warm start；
3. 以最大 objective 选定 `best_trial_number`；
4. 用该 trial 的固定参数重放一次门控、选段和 ARX，开启 Test 评价；
5. 保存 `test_free_run_fit`、Test one-step 与 free-run 的模式明确指标，以及下述泛化差距到 `statistics.evaluations.final_test` 和 `optimization.final_test` ProcessingRun。

最终 Test evaluation 失败不会伪造数值：Study 的寻优结果仍可查询，但 Test 字段为空并带错误状态。

## 指标定义

- Baseline validation FIT：正式 Baseline 的 validation free-run FIT；
- Optimized validation FIT：validation objective 选出的 best trial 的 validation free-run FIT；
- Optimized test FIT：best trial 固定后得到的 held-out Test free-run FIT；
- Improvement：`optimized_validation_fit - baseline_validation_fit`；
- Generalization gap：`optimized_validation_fit - optimized_test_fit`。

## 一步预测与自由仿真

同一个 ARX 在两种预测模式下的分数不能混写为无前缀的“Test 指标”：

| 模式 | 历史输出来源 | 用途 |
| --- | --- | --- |
| One-step | 每一步均使用真实历史输出 `y(k-1..k-na)` | 诊断短期回归/噪声拟合能力 |
| Free-run | 分区起点前仅以真实输出暖启动；之后连续使用模型自身预测 | 正式动态泛化与稳定性评价 |

两类数据分别保存在 `ArxMetrics.one_step.{train,validation,test}` 与
`ArxMetrics.free_run.{train,validation,test}`，每个对象都可以包含 MAE、RMSE、R²、FIT、NRMSE。
旧字段 `test_r2`、`test_rmse`、`mae`、`nrmse` 为 **one-step 兼容别名**；
`*_free_run_fit` 为 **free-run 兼容别名**。新接口、Dashboard 和报告代码不得再使用没有预测模式的字段名。

对同一组已对齐的 `y` 和 `y_hat`，当前代码采用：

```text
SSE = Σ(y - y_hat)²
SST = Σ(y - mean(y))²
R² = 1 - SSE / SST
FIT = 100 × (1 - ||y - y_hat||₂ / ||y - mean(y)||₂)
```

因此，在 `SST > 0`、同一模式、同一批样本且 FIT 未触发下限时：

```text
FIT = 100 × (1 - √(1 - R²))
```

`fit_percentage` 对自由仿真保留历史的 `-100%` 下限，故极差的自由仿真不必满足上式。
One-step R² 很高而 free-run FIT 很低并不矛盾：前者每一步被真实历史输出纠正，后者会暴露递推误差累积。

MAE、RMSE、R²必须随 `one_step_` 或 `free_run_` 前缀展示；FIT 的正式闭环主口径始终是 validation/test free-run FIT。

## Dashboard

Dashboard 仅以真实数据库记录显示上述指标。历史 Study 没有正式 Baseline 或 final Test evaluation 时：

- baseline / improvement 显示 `—`；
- Test FIT / gap 显示“暂无测试集评价”；
- 禁止用第一个 trial、固定值或前端计算补充缺失值。

泛化风险为系统工程提示，不是行业标准或“模型必然失效”的结论：gap ≤ 10 个百分点为正常，10–25 为注意，>25 为高风险。阈值统一位于 `evaluation_policy.py`。

## 只读泛化诊断

`GET /api/v1/optimization/optuna/{study_id}/diagnostics` 只重放已经由 Validation 固定的 Best Trial，输出按评分样本对齐的 Train/Validation/Test 分布、活动度、回归矩阵秩/条件数、预白化互相关峰、残差白度、one-step/free-run 指标与极点稳定性。它不会调用 Optuna、创建 Trial、写入 Study，也不会用 Test 修改最佳参数。
