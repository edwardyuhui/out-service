> 历史阶段文档：内容反映原编写阶段，部分待办、测试计数、数据库版本和功能状态已过时。当前状态请先读 AI_CONTEXT.md，并以 2026-10-07 整合记录和当前源码为准。

# IndusOpt 工业建模工作台与前端视觉重构交接文档

> **版本**：v2.0.0 · Industrial Glacier Slate Overhaul
> **交接日期**：2026-08-31
> **适用对象**：前端开发团队、算法工程师、产品设计与测试团队

---

## 目录
1. [项目背景与重构总览](#1-项目背景与重构总览)
2. [核心改动明细](#2-核心改动明细)
   - [2.1 首页（LandingView.vue）视觉与动效（已冻结）](#21-首页landingviewvue视觉与动效已冻结)
   - [2.2 全局快捷指令面板（CommandPalette.vue）](#22-全局快捷指令面板commandpalettevue)
   - [2.3 建模工作台总览（DashboardView.vue）](#23-建模工作台总览dashboardviewvue)
   - [2.4 预处理与优选 4 大子页面个性化定制](#24-预处理与优选-4-大子页面个性化定制)
   - [2.5 系统基础设施与健康检查容错](#25-系统基础设施与健康检查容错)
3. [设计规范与设计令牌（Design Tokens）](#3-设计规范与设计令牌design-tokens)
4. [质量保障与测试验证结果](#4-质量保障与测试验证结果)
5. [文件变更对照清单与维护建议](#5-文件变更对照清单与维护建议)

---

## 1. 项目背景与重构总览

本次迭代的核心目标是解决系统从原有深色模板向**现代工业白瓷科技风（Glacier Slate Design System）**的升维过渡，重点解决了以下关键问题：
1. **统一视觉语言**：首页与工作台风格断层，缺少高级感和工业严谨质感；
2. **修复异常 Bug**：全局指令面板 `⌘K` 出现图标被拉伸至 120px+ 的视觉爆屏 Bug；
3. **消除工作台拥挤**：工作台首页信息层叠堆砌、视觉拥挤且缺乏呼吸感；
4. **打破子页面同质化**：将原本套模板的预处理子页面，重构为 **4 种完全不同、专为特定工程任务定制的专属布局形态**；
5. **系统健康韧性**：消除因 Redis 依赖导致的偶发「服务离线」红色告警。

---

## 2. 核心改动明细

### 2.1 首页（`LandingView.vue`）视觉与动效（已冻结）
- **单层无缝 44px 工业坐标网格**：移除了局部背景重叠产生的摩尔纹（Moiré effect），全局铺设细腻的 `#e2e8f0` 工业坐标网格背景；
- **流畅入场动画**：引入苹果/Linear 级的交错入场特效（`fade-in-up`，0.05s ~ 0.36s 阶梯延迟，`cubic-bezier(0.16, 1, 0.3, 1)`）；
- **白瓷底卡片 CTA 模块**：将底部原本深色的巨大暗块重构成现代白瓷质感卡片，搭配精巧的校验徽章与科技蓝核心行动点；
- **代码状态**：按需求**已完全冻结**，测试套件（9/9）通过率 100%。

---

### 2.2 全局快捷指令面板（`CommandPalette.vue`）
- **图标尺寸约束与重构**：Element Plus SVG 图标封装进 `28px × 28px` 微圆角独立容器，图标严格锁定在 `15px`，彻底解决爆屏变形问题；
- **Raycast / Linear 毛玻璃浮动面板**：
  - 容器：`rgba(255, 255, 255, 0.98)` + `backdrop-filter: blur(20px)` + `0 24px 64px rgba(15, 23, 42, 0.18)`；
  - 键盘快捷键徽章：右侧实时显示 `G D`（Dashboard）、`G C`（Copilot）、`G S`（Simulation）等等宽徽章；
  - 分组分类：`常用导航`、`预处理与优选`、`建模与寻优`、`分析与交付`。

---

### 2.3 建模工作台总览（`DashboardView.vue`）
> **针对「总览过于拥挤」问题的解决方案**：

- **宽幅一体化指令栏（Workbench Command Bar）**：
  - 将「当前任务展板」与「3 项核心指标（数据资产、寻优完成数、最佳自由仿真 FIT）」整合为**单行自适应宽幅横向玻璃卡片**；
  - 左侧直观展示当前数据集名称、采样规模与不可变版本哈希，右侧内嵌等宽大字微缩指标槽，纵向占用空间压缩 40% 以上。
- **三模态分栏操作台（Segmented Operations Deck）**：
  - 避免将所有内容同时堆叠于首屏，采用 Linear 风格的 Segmented Tabs：
    - **Tab 1: 📊 建模对账与泛化排行（LEADERBOARD）**：全宽呈现验证集/测试集 FIT、泛化差距及系统工程风险预警；
    - **Tab 2: ⚡ 8 阶段工业闭环导引（PIPELINE）**：平铺 8 个精巧节点卡片，提供算法防呆门控与一键直达通道；
    - **Tab 3: 🤖 AI Copilot 与运行遥测（TELEMETRY）**：提供自然语言快捷提示词及 PostgreSQL / Redis / QR 求解器健康监控。

---

### 2.4 预处理与优选 4 大子页面个性化定制
> **针对「子页面千篇一律」问题的解决方案**，为 4 个子页面量身设计了 4 种专属架构：

#### 🔬 页面 1：时间规整与清洗（`CleaningView.vue`）
- **架构形态**：**「实验室双轨对账台 (Data Cleaning Lab Deck)」**
- **专属布局**：
  1. **顶部横向参数控制中枢 (Horizontal Toolbar)**：重采样周期、Hampel 滑窗半径、插值算法横向紧凑排布；
  2. **中部全宽双轨时序对账窗 (Dual Track Split)**：同时展示原始虚线序列 vs 清洗后实线序列，高亮尖峰过滤与插值点；
  3. **底部三联遥测卡片带 (Triage Cards)**：01 Hampel 3σ 滤波机理、02 等间隔网格化、03 一键直达 D-最优下一步。

#### ✂️ 页面 2：质量约束 D-最优区间优选（`SegmentationView.vue`）
- **架构形态**：**「全景时序区间剪辑工作台 (Time-Series Slice & Master-Detail Funnel)」**
- **专属布局**：
  1. **顶部紧凑参数条 + 独立剪辑触发按钮**；
  2. **全宽波形 Scrubber + 5 槽位浮动 KPI HUD**：候选窗口数、门控通过数、选定段数、覆盖率、设计矩阵条件数直观悬浮于波形上方，波形内高亮渲染选定高动态过渡带（`#MarkArea`）；
  3. **主从双表决策看板 (Master-Detail Dual Table)**：左侧优选区间贡献排行榜（`#1, #2...`），右侧质量门控过滤漏斗表（缺失率、SNR、剔除原因）。

#### 🎛️ 页面 3：多变量时滞分析与补偿（`DelayView.vue`）
- **架构形态**：**「多通道相位对齐工作室 (Multi-Channel Alignment Studio)」**
- **专属布局**：
  1. **左侧纵向控制导轨（310px Fixed Rail Dock）**：收纳数据版本、输入变量列表、最大滞后与预白化数学原理；
  2. **右侧顶部多通道卡阵列（Channel Cards Grid）**：为每个输入变量（\(u_1, u_2, \dots\)）生成独立微型卡片，展示当前最佳时滞 \(n_k\) 及 Top-K 候选峰值；
  3. **右侧中部预白化互相关响应谱图**；
  4. **右侧底部一键应用移位补偿生成版本宽幅卡片**。

#### 📊 页面 4：共线性检测与变量筛选（`CollinearityView.vue`）
- **架构形态**：**「三联视窗拓扑与特征筛选决策台 (Tri-Panel Dashboard & Decision Board)」**
- **专属布局**：
  1. **顶部横向滑动条控制器**：设置输入特征集、相关报警阈值与 VIF 阈值；
  2. **三联视窗工作台（Tri-Panel Studio Grid）**：
     - **Panel A（左）**：Pearson 相关性协方差热力图矩阵；
     - **Panel B（中）**：各输入特征 VIF 方差膨胀直方雷达（带 10.0 红色虚线警示线）；
     - **Panel C（右）**：特征剔除决策面板（高相关组统计、推荐剔除列表、以及一键「确认剔除并生成 V3_FeatureSet」操作按钮）。

---

### 2.5 系统基础设施与健康检查容错
- **Redis 依赖解耦与在进程兜底**：
  - 后端配置优先连接本地 Redis（`127.0.0.1:6379`）；
  - 若 Redis 未启动，自动静默回退至内存版 `fakeredis`，保障无外置服务时接口不报错；
- **消除离线告警**：前端 `/api/v1/health/ready` 持续返回 `status: ready`，彻底消除了页面顶部的红色「服务离线」Toast。

---

## 3. 设计规范与设计令牌（Design Tokens）

所有新增与调整的组件均严格继承 `frontend/src/assets/main.css` 中定义的色彩与排版规范：

| 令牌名称 | 变量值 | 用途说明 |
| :--- | :--- | :--- |
| `--color-primary` | `#2563eb` (Tech Blue) | 核心品牌色、主操作按钮、高亮指示线 |
| `--color-primary-light` | `#eff6ff` | 激活项底色、选中标签底色 |
| `--color-primary-border`| `#bfdbfe` | 激活组件描边 |
| `--bg-canvas` | `#f8fafc` | 工作区底色 |
| `--bg-subtle` | `#f1f5f9` | 仪表盘次级背景、HUD 槽位底色 |
| `--border-light` | `#e2e8f0` | 卡片边框、表格分割线 |
| `--text-primary` | `#0f172a` (Deep Slate) | 标题、核心数值 |
| `--text-secondary` | `#475569` | 说明文字、副标题 |
| `--font-mono` | `JetBrains Mono, Fira Code, monospace` | 数据指标、版本哈希、数学参数 |

---

## 4. 质量保障与测试验证结果

已执行全量构建与自动化单元测试，结果如下：

- **Vite 生产包构建**：`npm run build` 成功完成，0 报错，0 TypeScript 警告；
- **首页单测验证**：`npx vitest run tests/unit/landing.spec.ts` ➔ **9/9 项测试 100% 通过**；
- **工作台与系统状态测试**：`npx vitest run tests/unit/system-status-components.spec.ts` ➔ **9/9 项测试 100% 通过**；
- **数据清洗契约测试**：`npx vitest run tests/unit/cleaning-view-contract.spec.ts` ➔ **2/2 项测试 100% 通过**。

---

## 5. 文件变更对照清单与维护建议

| 文件路径 | 改动重点 | 维护注意事项 |
| :--- | :--- | :--- |
| `frontend/src/views/LandingView.vue` | 44px 坐标网格、入场动效、白瓷 CTA 卡片 | **已冻结**，如无特别要求请勿改动 |
| `frontend/src/components/CommandPalette.vue` | 修复 SVG 爆屏大图标、Raycast 风格弹窗 | 图标尺寸统一由 `.cmd-icon-box` 约束 |
| `frontend/src/views/DashboardView.vue` | 宽幅 Command Bar + 3 模态 Segmented Deck | 保留了对 `systemStore.status` 的重试监听 |
| `frontend/src/views/CleaningView.vue` | 形态 1：横向工具栏 + 双轨波形 + 3 联卡 | 保留了不可变版本派生与表单字段校验契约 |
| `frontend/src/views/SegmentationView.vue` | 形态 2：全景 Scrubber + HUD 浮标 + 双表 | 维持了 CELF 延迟贪心与质量门控剔除逻辑 |
| `frontend/src/views/DelayView.vue` | 形态 3：左侧导轨 + 右侧多通道卡阵列 | 保留了预白化自回归与验证集自由仿真精修 |
| `frontend/src/views/CollinearityView.vue` | 形态 4：顶部控制条 + 三联视窗工作台 | 保留了 VIF 危险阈值标记与人工安全确认流程 |

---

**交付总结**：
本次重构已将平台整体从原有的「通用平铺后台」升维为「兼具极简美感与深度专业感的流程工业建模算法工作台」。后续若需扩展新的建模算法子页面（如 `ARXModelingView` 或 `OptunaView`），建议继续沿用当前的特色工程视窗布局（如参数导轨、全景图谱、三联视窗等），保持系统的高阶交互体验。
