# 给 AI 的项目上下文

整理日期：2026-10-30。这个仓库是用户本地项目的精选源码快照，目标是让另一个 AI 能理解我们在做什么、怎么做、目前做到了哪里，并继续协助开发和答辩。

## 建议先读这些

1. 本文件和 [README](README.md)：定位、实现与边界。
2. [项目完整介绍](docs/project/项目完整介绍.md) 与 [事实核对](docs/project/事实核对与旧稿勘误.md)：当前对外讲述的事实底稿。
3. [2026-10-07 平台整合](docs/integration-20261007.md)：最新已记录的实际软件运行与相关验收。
4. [需求核查](docs/requirements/implementation-audit-20261004.md)：OR-01 至 OR-12 功能对应与阶段证据，含 10 月 5 日补充。
5. [17 页答辩策划](docs/presentation/20261030/17页叙事与内容策划.md) 和 [官方评审依据及调整建议](docs/presentation/20261030/官方评审依据与PPT调整建议.md)：10 月 30 日的工作方向。后者对第 14–16 页有进一步调整建议；这些是策划文稿，不代表新 PPT 已完成。
6. 需要开发时再读架构、算法、API、服务和对应测试。

历史阶段计划、PHASE_STATUS、早期 HANDOVER、backend/README 和历史实验报告保留了当时状态。出现冲突时，不把旧待办、旧测试计数或旧模型指标当作当前状态；结合日期、实际源码与上述最新记录判断。某些旧记录关联的原始文件没有纳入精简包。

## 我们在做什么

项目名 IndusOpt 工模智优，序衡团队。参加 2026“数字马力杯”第十三届浙江省大学生服务外包创新应用大赛 A14（和利时）。

目标用户是流程工业建模工程师：拿到的历史时序很多，但长稳态、重复响应、噪声、时滞和冗余变量让可辨识信息难找。平台把原本分散的数据准备、动态片段选择、模型评价、反馈调整和成果交付串起来。

工作流：CSV 上传 → 画像/异常 → 清洗规整 → 质量门控和 D-最优选段 → 时滞及确认补偿 → 共线性及确认变量 → 初始辨识 → Optuna 寻优 → 冻结 Test 回放 → 图文报告 → CSV/Manifest。

“闭环”指数据选择与建模评价反馈。当前交付是建模准备和辨识辅助，没有直接控制真实工业装置的证据。用户输入自然语言后，Agent 组织工作；算法和服务负责实际计算与持久化。

## 怎么做：代码地图

| 模块 | 关键入口 | 看什么 |
|---|---|---|
| API 与配置 | `backend/app/main.py`、`app/api/routes.py`、`app/core/config.py` | 应用入口、路由、环境参数 |
| 数据资产 | `app/services/dataset_service.py`、`dataset_version_io.py`、`version_provenance_service.py` | CSV、派生版本和血缘 |
| 清洗 | `algorithms/cleaning/`、`app/services/cleaning_service.py` | 缺失、异常、规整与质量 |
| 核心数据优选 | `algorithms/identifiability/gating.py`、`selection.py`、`regressor.py`、`app/services/segment_service.py` | 质量门控、回归特征、信息增益与选段 |
| 时滞与共线性 | `identifiability/delay.py`、`collinearity.py`、`app/services/versioned_preprocessing_service.py` | 分析与确认后的版本化操作 |
| 建模评价 | `identifiability/estimation.py`、`validation.py`、`app/services/modeling_service.py` | 标准化、ARX/FIR、自由仿真与冻结评价 |
| 实验 OE | `identifiability/output_error.py`、`multihorizon.py` | 稳定参数化与多步模拟训练 |
| 反馈寻优 | `app/services/optimization_service.py`、`optimization_feedback_policy.py`、`evaluation_policy.py` | 搜索、Validation、反馈预算与最优模型 |
| Agent 规划约束 | `algorithms/agent/`、`app/services/agent_service.py` | LLM/规则计划、白名单与合规校验 |
| Agent 执行 | `app/services/agent_execution_service.py`、`agent_tool_adapter.py`、`agent_*_service.py` | 执行状态、确认、真实工具调用 |
| 报告与数值出处 | `algorithms/report/provenance.py`、`app/services/report_service.py` | 占位符绑定、实际图表与报告 |
| 数据库与队列 | `backend/alembic/`、`app/models/`、`app/worker.py`、`app/services/job_queue.py` | 迁移、模型持久化、RQ |
| 前端工作台 | `frontend/src/views/WorkspaceView.vue`、`components/workspace/`、`components/artifact/` | 计划、确认、执行和成果 |
| 前端业务页 | `frontend/src/views/`、`api/`、`stores/`、`types/api.ts` | 数据、预处理、建模、寻优、历史、交付 |
| 启动与配置 | `scripts/run_platform.py`、`docker-compose.yml`、`frontend/nginx.conf` | 一键本地运行与容器配置 |
| 测试与实验 | `backend/tests/`、`frontend/tests/`、`frontend/e2e/`、`backend/scripts/benchmark_*.py` | 行为约束和可复现计算 |

表中省略 `backend/` 的 `app/`、`algorithms/` 都位于后端目录；前端路径均以仓库根目录为起点。

## 已验证到哪里

- 最近软件整合证据为 2026-10-07：真实锅炉 13 步成功，DeepSeek 规划与报告无回退，6 幅图、54 个绑定数值全部解析，导出 3172 行。
- 同一锅炉案例：原始 86400 行 → 60 秒聚合 7200 → 时滞补偿 7111 → 最终优选导出 3172。初始 1200 行选段与最终导出是不同阶段。
- 冻结 Test：1391 点，自由仿真 RMSE 1.8870457963、FIT 49.55033176%，存在输入范围外推。FIT 是拟合指标，不能写成分类准确率或控制达标。
- 4 次 Trial 中最佳是第 0 次，仅证明流程完成，不能宣称反馈提升或搜索收敛。
- 双水箱：独立测试记录，模型部分对照；多步 OE 相比最初估计器 RMSE 下降 37.48%，单段 OE 略好，求解预算不等。不能推广为整个系统提升。
- 卷绕：同次运行的时间留出，两个输出 RMSE 改善 24.24% / 10.82%，候选预算不等，不能归因于反馈或算作两个独立工厂。
- 蒸馏：跨运行迁移仍失败，必须保留失败结论。已经查看过的目标只算开发回归。
- OE 有 API/前端实验入口，尚未进入默认 Agent/Optuna 自动搜索。
- 原记录中的 70 后端 / 18 前端是 10 月 7 日相关检查；历史全量 718 后端 / 282 前端属于更早批次，不能相加当作本次全量结果。本次整理上传不表示重新执行过这些测试。
- 本地 PostgreSQL、Redis、前后端运行和重启恢复已有记录；Docker Compose 仅配置检查通过，镜像构建/运行待实机验收。

## 后续工作的上下文

当前最新材料围绕 **10 分钟、17 页答辩**：以同一锅炉数据讲工程师任务、实际平台、互补选段、反馈、Agent 真实执行与可复核交付。官方评审依据另建议补足可核实团队角色、部署条件与成本、试点方案和问答准备。

技术后续重点：补齐真实工况与激励覆盖；预先固定新的训练、Validation 和独立 Test 运行；比较局部模型/合理校准；用更充分预算验证反馈价值；完成容器实机验收。没有核实的成员角色、客户、企业部署、商业收益和成本金额不要补写。

## 修改时必须保留的业务语义

- 原始数据不覆盖；处理产生版本，模型与导出指向真实来源。
- 训练/Validation/Test 按时间和历史保护隔离；Test 不参与调参或重拟合，不能按 Test 结果改赢家。
- 质量门控先于信息准则，不能默认 D-最优总优于其他策略；欠激励时不能编造响应。
- LLM 提议、白名单校验和用户确认各有职责；正式流程中的确认节点要保留。
- 报告中的数字来自实际绑定证据，缺数据时明确缺失，不能伪造曲线和实验成绩。
- 无模型配置时保留确定性离线路径。密钥只放后端私有配置。
- 实验入口、正式默认行为和未来计划分别描述，沿用报告中的评价协议。

## 此快照的局限

源码和核心文档已保留，但没有原始工业 CSV、本地数据库、云端凭据、完整封存日志、全部大型候选结果、比赛报名材料、专利草稿、PPT 和视频。报告中的原始绝对路径属于原电脑，要在新机器重新准备数据并配置；部分证据链接指向未上传内容，不能假装已查阅。历史 Git SHA 用于解释旧实验版本，本仓库没有继承原仓库的 Git 历史。

精确文件列表见 `docs/UPLOAD_MANIFEST.json`。修改前先查看相应源码和测试，文稿描述不能替代代码核验。
