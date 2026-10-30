# ProcessPilot 不可变数据版本与预处理流水线

## 生命周期

所有会改变 CSV 内容的操作都创建新的 `DatasetVersion`，从不覆盖父版本或其文件：

```text
upload / simulation_generate (V0)
  → preprocessing.clean
  → preprocessing.lag_compensation
  → preprocessing.feature_selection
```

每个版本保存 Dataset FK、父版本、递增版本号、operation、参数 JSON、CSV artifact、SHA-256、行列数、有效时间范围与创建时间。每次转换还创建一条 `ProcessingRun`，记录 source/result version、参数、摘要、状态与时间；对应 `DatasetProfileRecord` 必须由新 CSV 重算。

版本 CSV 使用 `derived/{dataset_id}/{version_id}.csv`，因此不会受原始文件名、同名上传或 Windows 非法字符影响。

## Analyze 与 Apply

`/preprocessing/delay` 与 `/preprocessing/collinearity` 是只读分析：它们只保存审计 `ProcessingRun`，不会替换 active version。

`/preprocessing/delay/apply` 和 `/preprocessing/features/apply` 是显式 Apply：都要求 `user_confirmed=true`，否则返回 `CONFIRMATION_REQUIRED`。这使未来 Agent 只能先分析、展示证据、获得确认，再调用会改变资产的工具。

## 时滞补偿语义

项目 ARX 使用：

```text
y(k) = ... + b × u(k-nk) + e(k)
```

因此对 `nk=d`，补偿版本保持输出和时间轴不变，并写入：

```text
u_aligned(t) = u_source(t-d)
y_aligned(t) = y_source(t)
```

为避免首端没有 `u(t-d)`，Apply 会删除开头 `max(lag_map)` 行；尾端不补空值。完成补偿后，使用这些已经对齐的输入做 ARX 时应把对应输入的 `nk` 设为 `0`。Delay 分析无法提供可靠证据时不应自动调用 Apply。

## 变量剔除语义

Feature Apply 仅允许删除已确认的 input 列；时间列和 output 列受保护，并且至少保留一个 input。请求保存 `recommendation_source`、每个被删变量的 reason/metric/threshold/related variables 等 evidence，服务不因 VIF 超阈值而静默删列。

## 下载和血缘

`GET /datasets/{dataset_id}/versions` 返回 parent、operation、行列数、artifact 与关联 ProcessingRun。`GET /datasets/{dataset_id}/download?version_id={uuid}` 与 `GET /datasets/{dataset_id}/profile?version_id={uuid}` 分别下载或读取任意不可变版本；未指定时使用 active version。
