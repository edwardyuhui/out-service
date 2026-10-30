# 平台整合与答辩交付 · 2026-10-07

## 已完成

- 新增一条命令启动入口 `scripts/run_platform.py`，建立持久化独立 PostgreSQL、Redis，迁移数据库并启动前后端同源访问。
- Compose 补齐前端 Nginx、后端迁移、健康探针及 Worker 启动依赖；前后端 Docker 构建上下文排除凭据和本地数据。
- 修正首页工作流范围：优化数据优选及建模参数。补齐 Agent 真实工具名的中文显示，修复长输出变量名溢出。
- 使用后端既有 DeepSeek Flash 配置，在真实锅炉数据上执行云端规划、真实算法、冻结 Test、云端报告、数据导出完整流程。
- 沿用项目重新设计版模板，制作 20 页答辩 PPT。加入实际平台截图、原始算法对照、泛化失败边界、可编辑图表及原生动画。
- 既有 DeepSeek API 生成 20 页口播草稿，经逐页事实核对并匹配最终页序后写入备注；原模板保留。

## 实机证据

| 检查 | 结果 |
|---|---|
| 数据库 | PostgreSQL 从空库迁移至 Alembic 0007；重启后保留任务 |
| 云端规划 / 报告 | 均来自 DeepSeek Flash，均无回退 |
| Agent | 13 个步骤全部成功 |
| 报告 | 6 幅图、54 个绑定数值，全部解析 |
| 导出 | 3172 / 7111 行，清单关联最优冻结模型 |
| 浏览器 | 13 个成果入口，刷新后完成状态恢复，无 pageerror |
| 浏览器下载 | CSV 与后端 HTTP 下载逐字节一致 |
| 软件检查 | 70 项后端 API / Agent / 报告测试、18 项相关前端测试通过；Vue 类型检查、构建、Ruff 通过 |
| PPT | 20 页，3 个原生图表、3 个原生表格；20 个淡入转场、32 个进入动画 |

本次测试更新了两处旧的英文工具名显示断言，使其符合新增中文标签；保留了字体与数值格式断言。未更改算法数值断言。

## 运行与演示

仓库根目录：

```bash
python3 scripts/run_platform.py
```

已有构建使用 `--skip-build`。依赖为现有 backend/.venv、前端 npm 依赖、PostgreSQL 16 与 Redis。浏览器：<http://127.0.0.1:5173>。

本次任务：<http://127.0.0.1:5173/workspace/90b90851-9137-4b68-bf71-c64bf462e00c>。

私有持久化文件在忽略目录 `.runtime/platform`；API 从 `backend/.env` 读取配置，不复制凭据。复跑真实演示（会新增数据与任务）：

```bash
cd backend
.venv/bin/python scripts/run_live_demo.py --manifest ../docs/experiments/generalization-20261003/data-manifest.json --out ../.runtime/platform/demo-repeat
```

该 manifest 指向本机已下载的公开工业数据目录，换机器需要先按源记录准备 CSV 并修改 manifest 路径。

交付目录：`output/答辩整合版`，包含 PPT、口播稿、HTML 报告、CSV、Manifest 与验收记录。

## 口径与剩余验证

- 独立双水箱测试中多步 OE 相对最初估计器 RMSE 降低 37.48%，只属于模型部分对照；单段 OE 略好于多步 OE。
- 真实锅炉 Test 自由仿真 RMSE 1.8870、FIT 49.55%，存在输入外推；FIT 不是分类准确率。
- 四次 Trial 为流程演示预算，最佳候选为 Trial 0，尚未证明收敛。
- 蒸馏跨工况回归仍失败，不能宣称普遍泛化已解决；PPT 保留失败结果。
- Compose 配置检查通过；本机 Docker daemon 不可用，镜像构建与容器启动未实机验收。
- PPT 已逐页渲染检查及原生动画 XML 校验；未在 PowerPoint 客户端实际放映验收。动画在放映模式中查看。
