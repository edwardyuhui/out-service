<template>
  <div class="page-container dataset-detail-view">
    <PageHeader
      v-if="dataset"
      eyebrow="PREPARE DATA / DATASET DETAILS"
      :title="dataset.name"
    >
      <template #description>
        当前版本：<span class="code-inline">{{ shortIdentifier(dataset.version_id || dataset.latest_version_id) }}</span>
        <el-tooltip :content="dataset.version_id || dataset.latest_version_id" placement="top">
          <span class="version-id-help">查看完整 ID</span>
        </el-tooltip>
        · 来源：<el-tag size="small" type="info">{{ dataset.source || 'upload' }}</el-tag>
      </template>
      <template #actions>
        <el-button type="primary" size="default" icon="Opportunity" @click="openCleaning">
          进入清洗实验室
        </el-button>
      </template>
    </PageHeader>

    <el-tabs v-model="activeTab" type="card" class="detail-tabs">
      <!-- Tab 1: Overview & Time-Series Plot -->
      <el-tab-pane label="概览与多变量时序预览" name="overview" class="overview-tab-pane">
        <div class="preview-tab-content">
        <div v-if="dataset?.source === 'simulation'" class="industrial-card simulation-overview-card">
          <div class="industrial-card-header">
            <div class="industrial-card-title">
              <el-icon><DataLine /></el-icon> 仿真真值概览
            </div>
            <el-tag type="success" effect="plain">来自仿真根版本 V0</el-tag>
          </div>
          <dl class="simulation-overview-grid">
            <div><dt>数据集名称</dt><dd>{{ dataset.name }}</dd></div>
            <div><dt>原始样本量</dt><dd>{{ simulationValue(dataset.simulation?.original_row_count) }}</dd></div>
            <div><dt>原始物理字段</dt><dd>{{ simulationList(dataset.simulation?.physical_columns) }}</dd></div>
            <div><dt>系统类型</dt><dd>{{ simulationValue(dataset.simulation?.system_type) }}</dd></div>
            <div><dt>真实阶数 na</dt><dd>{{ simulationValue(dataset.simulation?.true_na) }}</dd></div>
            <div><dt>真实阶数 nb</dt><dd>{{ simulationList(dataset.simulation?.true_nb) }}</dd></div>
            <div><dt>真实滞后 d_true</dt><dd>{{ simulationMap(dataset.simulation?.true_delays_by_input) }}</dd></div>
            <div><dt>噪声水平 σ</dt><dd>{{ simulationValue(dataset.simulation?.noise_level) }}</dd></div>
          </dl>
          <p v-if="!dataset.simulation" class="simulation-missing-note">
            该仿真数据集没有可验证的根版本元数据，历史真值未记录。
          </p>
        </div>
        <StateView
          class="preview-state"
          v-if="detailLoading"
          state="loading"
          title="正在加载真实数据预览…"
        />
        <div v-else-if="detailError" class="industrial-card preview-error">
          <el-alert
            type="error"
            title="数据预览加载失败"
            :description="detailError"
            :closable="false"
            show-icon
          />
          <el-button type="primary" plain @click="fetchDetail">重新加载</el-button>
        </div>
        <div class="industrial-card preview-card" v-else-if="dataset">
          <div class="industrial-card-header">
            <div class="industrial-card-title">
              <el-icon><DataLine /></el-icon> 多变量数据预览
            </div>
          </div>

          <el-alert
            v-if="previewError"
            class="preview-page-error"
            type="error"
            title="数据预览加载失败"
            :description="previewError"
            :closable="false"
            show-icon
          />
          <StateView
            v-if="previewLoading && previewRows.length === 0"
            class="preview-state"
            state="loading"
            title="正在加载当前版本数据预览…"
          />
          <div
            v-else-if="previewRows.length > 0"
            v-loading="previewLoading"
            class="preview-table-region"
            :aria-busy="previewLoading"
          >
            <el-table class="preview-table" :data="previewRows" stripe>
              <el-table-column v-for="col in previewColumns" :key="col" :prop="col" :label="col" min-width="130">
                <template #default="scope">
                  <span :class="{ 'preview-null': scope.row[col] === null }">
                    {{ formatPreviewValue(scope.row[col]) }}
                  </span>
                </template>
              </el-table-column>
            </el-table>
          </div>
          <div v-else-if="!previewError" class="preview-empty">
            该版本文件不包含可预览的数据行
          </div>
          <div
            v-if="previewTotalItems > 0"
            class="preview-pagination-bar"
            :data-total-pages="previewTotalPages"
          >
            <strong class="preview-page-range" aria-live="polite">{{ previewRangeLabel }}</strong>
            <el-pagination
              :current-page="previewPage"
              :page-size="previewPageSize"
              :page-sizes="[50, 100, 200]"
              :total="previewTotalItems"
              :disabled="previewLoading"
              layout="sizes, prev, pager, next"
              @current-change="handlePreviewPageChange"
              @size-change="handlePreviewPageSizeChange"
            />
          </div>
        </div>
      </div>
      </el-tab-pane>

      <!-- Tab 2: Quality Profile -->
      <el-tab-pane label="★ 真实数据质量诊断报告" name="profile">
        <StateView v-if="profileLoading" state="loading" title="正在生成真实数据质量 Profile..." />

        <div class="industrial-card" v-else-if="profile">
          <div class="profile-score-box">
            <div class="score-num" :class="{ warning: profile.quality_score < 80 }">
              {{ profile.quality_score }} <span class="max">/ 100 分</span>
            </div>
            <div class="score-desc">
              <div class="title">数据质量诊断结论: {{ profile.quality_score >= 80 ? '良好' : '存在质量缺陷 (需清洗规整)' }}</div>
              <p>
                总体缺失率: {{ (profile.missing_rate * 100).toFixed(2) }}% |
                不规则采样率: {{ ((profile.irregular_sampling_rate || 0) * 100).toFixed(2) }}% |
                {{ candidateFreezeSummary }}
              </p>
            </div>
          </div>

          <el-divider />

          <div class="freeze-segments" aria-label="候选异常冻结段">
            <h4>候选异常冻结段</h4>
            <p class="freeze-hint">
              连续恒值不必然代表仪表故障；仅展示相对该变量常规保持长度显著异常的候选区段。
            </p>
            <el-empty
              v-if="candidateFrozenSegments.length === 0"
              description="未检测到异常冻结段"
              :image-size="72"
            />
            <el-collapse v-else v-model="expandedFreezePanels">
              <el-collapse-item name="candidate-freezes">
                <template #title>
                  查看区段详情（首屏显示前 {{ candidateFrozenSegments.length > freezeSegmentDisplayLimit ? freezeSegmentDisplayLimit : candidateFrozenSegments.length }} 段，共 {{ candidateFrozenSegments.length }} 段）
                </template>
                <el-table :data="visibleCandidateFrozenSegments" stripe size="small" style="width: 100%">
                  <el-table-column prop="column" label="变量" min-width="130" />
                  <el-table-column prop="start_index" label="开始位置" min-width="110" />
                  <el-table-column prop="end_index" label="结束位置" min-width="110" />
                  <el-table-column prop="length" label="持续点数" min-width="110" />
                </el-table>
                <p v-if="candidateFrozenSegments.length > freezeSegmentDisplayLimit" class="freeze-limit-note">
                  为避免页面过长，当前仅显示前 {{ freezeSegmentDisplayLimit }} 段；完整结构化审计数据可通过 Profile API 获取。
                </p>
              </el-collapse-item>
            </el-collapse>
          </div>

          <!-- Column Missing Rates Breakdown -->
          <div style="margin-bottom: 20px">
            <h4>各变量缺失率分布</h4>
            <el-row :gutter="16" style="margin-top: 10px">
              <el-col :span="6" v-for="(rate, col) in profile.missing_rates" :key="col">
                <div class="stat-mini-card">
                  <div class="col-name">{{ col }}</div>
                  <div class="rate-val">{{ (rate * 100).toFixed(2) }}%</div>
                  <div class="sub-info">异常点: {{ profile.anomaly_counts[col] || 0 }}</div>
                </div>
              </el-col>
            </el-row>
          </div>

          <!-- Column Statistics Table -->
          <div style="margin-bottom: 20px" v-if="profile.column_statistics">
            <h4>变量统计量矩阵</h4>
            <el-table :data="formattedColStats" stripe style="width: 100%; margin-top: 10px">
              <el-table-column prop="col" label="变量名" width="120" />
              <el-table-column prop="count" label="有效行" width="100" />
              <el-table-column prop="mean" label="均值" />
              <el-table-column prop="std" label="标准差" />
              <el-table-column prop="min" label="最小值" />
              <el-table-column prop="max" label="最大值" />
              <el-table-column prop="q50" label="中位数 (Q50)" />
            </el-table>
          </div>

          <!-- Recommendations -->
          <div class="recommendations">
            <h4>预处理建议</h4>
            <ul>
              <li v-for="(rec, idx) in profile.recommendations" :key="idx">{{ rec }}</li>
            </ul>
          </div>

          <div style="margin-top: 20px">
            <el-button type="primary" icon="ArrowRight" @click="openCleaning">
              前往执行时间规整与异常清洗
            </el-button>
          </div>
        </div>
      </el-tab-pane>

      <!-- Tab 3: Version Lineage DAG -->
      <el-tab-pane label="数据版本血缘（DAG）" name="versions">
        <div class="industrial-card">
          <div class="industrial-card-header">
            <div class="industrial-card-title">
              <el-icon><Share /></el-icon> 版本演化记录
            </div>
          </div>
          <el-timeline v-if="versionNodes.length > 0">
            <el-timeline-item
              v-for="node in versionNodes"
              :key="node.id"
              :timestamp="node.created_at"
              :type="node.id === (dataset?.version_id || dataset?.latest_version_id) ? 'primary' : 'info'"
              placement="top"
            >
              <el-card>
                <div class="version-card">
                  <h4>{{ node.name }}</h4>
                  <dl class="version-basics">
                    <div><dt>版本 UUID</dt><dd class="audit-break">{{ node.id }}</dd></div>
                    <div><dt>父版本</dt><dd class="audit-break">{{ node.parent_version_id || '根版本' }}</dd></div>
                    <div><dt>操作类型</dt><dd>{{ operationLabel(node.tool) }}</dd></div>
                    <div><dt>创建时间</dt><dd>{{ formatDateTime(node.created_at) }}</dd></div>
                    <div><dt>行 / 列</dt><dd>{{ node.row_count }} / {{ node.column_count }}</dd></div>
                    <div><dt>文件路径</dt><dd class="audit-break">{{ node.artifact_path }}</dd></div>
                    <div v-if="node.processing_run_id"><dt>处理运行 UUID</dt><dd class="audit-break">{{ node.processing_run_id }}</dd></div>
                  </dl>

                  <div v-if="node.tool === 'preprocessing.clean'" class="audit-groups">
                    <section class="audit-group">
                      <h5>采样与插值</h5>
                      <dl class="audit-list">
                        <div><dt>目标采样周期</dt><dd>{{ cleaningDisplay(node, 'resample_period_seconds', 'target_sample_period_seconds') }}</dd></div>
                        <div><dt>插值方式</dt><dd>{{ cleaningDisplay(node, 'interpolation') }}</dd></div>
                        <div><dt>重复时间戳策略</dt><dd>{{ cleaningDisplay(node, 'duplicate_strategy') }}</dd></div>
                      </dl>
                    </section>
                    <section class="audit-group">
                      <h5>异常处理</h5>
                      <dl class="audit-list">
                        <div><dt>检测方法</dt><dd>{{ cleaningDisplay(node, 'outlier_detector', 'anomaly_detector') }}</dd></div>
                        <div><dt>处理策略</dt><dd>{{ cleaningDisplay(node, 'outlier_strategy', 'anomaly_strategy') }}</dd></div>
                        <div><dt>Hampel 窗口</dt><dd>{{ cleaningDisplay(node, 'hampel_window') }}</dd></div>
                        <div><dt>平滑方法</dt><dd>{{ cleaningDisplay(node, 'smoothing') }}</dd></div>
                      </dl>
                    </section>
                    <section class="audit-group">
                      <h5>处理结果</h5>
                      <dl class="audit-list">
                        <div><dt>唯一变更</dt><dd>{{ processingCount(node, 'unique_changed_cells') }}</dd></div>
                        <div><dt>缺失值填补</dt><dd>{{ processingCount(node, 'missing_value_fills') }}</dd></div>
                        <div><dt>异常值替换</dt><dd>{{ processingCount(node, 'outlier_replacements') }}</dd></div>
                        <div><dt>重复时间戳</dt><dd>{{ processingCount(node, 'duplicate_timestamps_processed', '行') }}</dd></div>
                        <div><dt>平滑修改</dt><dd>{{ processingCount(node, 'smoothing_changes') }}</dd></div>
                      </dl>
                    </section>
                    <section class="audit-group">
                      <h5>审计与告警</h5>
                      <dl class="audit-list">
                        <div v-if="legacyConstantCount(node) !== null"><dt>历史恒值区段审计数</dt><dd>{{ legacyConstantCount(node) }}段</dd></div>
                        <div v-else><dt>恒值区段审计数</dt><dd>{{ currentConstantCount(node) }}</dd></div>
                        <div><dt>候选异常冻结段</dt><dd>{{ candidateFreezeCount(node) }}</dd></div>
                      </dl>
                      <ul v-if="displayWarnings(node).length" class="audit-warnings">
                        <li v-for="warning in displayWarnings(node)" :key="warning">{{ warning }}</li>
                      </ul>
                    </section>
                  </div>

                  <div v-if="node.tool === 'simulation_generate'" class="audit-groups simulation-audit-groups">
                    <section class="audit-group provenance-summary">
                      <h5>仿真溯源</h5>
                      <dl class="audit-list">
                        <div><dt>证据来源</dt><dd>{{ node.provenance?.evidence_source || '未记录' }}</dd></div>
                        <div><dt>展示说明</dt><dd>用户请求与实际生效参数分层展示，原始字段保留在审计区。</dd></div>
                      </dl>
                    </section>
                  </div>

                  <div class="audit-evidence-chain" aria-label="审计证据链">
                    <section
                      v-if="node.tool === 'simulation_generate'"
                      class="audit-evidence-card"
                      :class="{ 'is-expanded': isAuditEvidenceExpanded(`${node.id}-request`) }"
                      data-audit-evidence="request"
                    >
                      <button
                        type="button"
                        class="audit-evidence-card__trigger"
                        :aria-expanded="isAuditEvidenceExpanded(`${node.id}-request`)"
                        :aria-controls="`audit-evidence-panel-${node.id}-request`"
                        @click="toggleAuditEvidence(`${node.id}-request`)"
                      >
                        <span class="audit-evidence-card__copy">
                          <span class="audit-evidence-card__title">用户请求参数</span>
                          <span class="audit-evidence-card__description">用户最初提交给系统的配置与目标</span>
                        </span>
                        <span class="audit-evidence-card__action">
                          {{ isAuditEvidenceExpanded(`${node.id}-request`) ? '收起' : '查看详情' }}
                          <span class="audit-evidence-card__action-icon" aria-hidden="true">
                            {{ isAuditEvidenceExpanded(`${node.id}-request`) ? '↑' : '→' }}
                          </span>
                        </span>
                      </button>
                      <div
                        v-show="isAuditEvidenceExpanded(`${node.id}-request`)"
                        :id="`audit-evidence-panel-${node.id}-request`"
                        class="audit-evidence-card__content"
                        data-audit-evidence-panel="request"
                      >
                        <div class="audit-structured request-parameters-view">
                          <p class="audit-section-note">以下为用户提交的原始请求值，最终结果以实际生效参数为准。</p>
                          <dl class="audit-list request-audit-list">
                            <div><dt>场景</dt><dd>{{ requestValue(node, 'scenario') }}</dd></div>
                            <div><dt>数据集名称</dt><dd>{{ requestValue(node, 'dataset_name', 'name') }}</dd></div>
                            <div><dt>样本数</dt><dd>{{ requestValue(node, 'num_samples', 'n_steps', '个采样点') }}</dd></div>
                            <div><dt>采样周期</dt><dd>{{ requestValue(node, 'sample_period_seconds', undefined, ' 秒') }}</dd></div>
                            <div><dt>输入变量数量</dt><dd>{{ requestValue(node, 'input_count', undefined, '个变量') }}</dd></div>
                            <div><dt>请求噪声水平</dt><dd>{{ requestRateValue(node, 'noise_level', false) }}</dd></div>
                            <div><dt>请求异常率</dt><dd>{{ requestRateValue(node, 'anomaly_rate', true) }}</dd></div>
                            <div><dt>请求缺失率</dt><dd>{{ requestRateValue(node, 'missing_rate', true) }}</dd></div>
                            <div><dt>随机种子</dt><dd>{{ requestValue(node, 'seed') }}</dd></div>
                          </dl>
                        </div>
                      </div>
                    </section>

                    <section
                      v-if="node.tool === 'simulation_generate'"
                      class="audit-evidence-card"
                      :class="{ 'is-expanded': isAuditEvidenceExpanded(`${node.id}-resolved`) }"
                      data-audit-evidence="resolved"
                    >
                      <button
                        type="button"
                        class="audit-evidence-card__trigger"
                        :aria-expanded="isAuditEvidenceExpanded(`${node.id}-resolved`)"
                        :aria-controls="`audit-evidence-panel-${node.id}-resolved`"
                        @click="toggleAuditEvidence(`${node.id}-resolved`)"
                      >
                        <span class="audit-evidence-card__copy">
                          <span class="audit-evidence-card__title">场景解析后实际生效参数</span>
                          <span class="audit-evidence-card__description">系统解析、校验并最终采用的正式参数</span>
                        </span>
                        <span class="audit-evidence-card__action">
                          {{ isAuditEvidenceExpanded(`${node.id}-resolved`) ? '收起' : '查看详情' }}
                          <span class="audit-evidence-card__action-icon" aria-hidden="true">
                            {{ isAuditEvidenceExpanded(`${node.id}-resolved`) ? '↑' : '→' }}
                          </span>
                        </span>
                      </button>
                      <div
                        v-show="isAuditEvidenceExpanded(`${node.id}-resolved`)"
                        :id="`audit-evidence-panel-${node.id}-resolved`"
                        class="audit-evidence-card__content"
                        data-audit-evidence-panel="resolved"
                      >
                        <div class="audit-structured resolved-parameters-view">
                          <section class="audit-subsection" data-audit-section="basic">
                            <h6>基础配置</h6>
                            <dl class="audit-list audit-basic-grid">
                              <div><dt>场景</dt><dd>{{ requestValue(node, 'scenario') }}</dd></div>
                              <div><dt>随机种子</dt><dd>{{ resolvedScalar(node, 'seed') }}</dd></div>
                              <div><dt>实际噪声水平</dt><dd>{{ resolvedScalar(node, 'noise_level') }}</dd></div>
                            </dl>
                          </section>

                          <section class="audit-subsection" data-audit-section="truth">
                            <h6>真实系统与参数</h6>
                            <dl class="audit-list audit-basic-grid audit-truth-grid">
                              <div><dt>系统类型</dt><dd>{{ resolvedScalar(node, 'system_type') }}</dd></div>
                              <div><dt>真实阶数 na</dt><dd>{{ resolvedScalar(node, 'true_na') }}</dd></div>
                              <div><dt>真实阶数 nb</dt><dd>{{ resolvedList(node, 'true_nb') }}</dd></div>
                              <div class="audit-truth-field--wide"><dt>真实滞后数组</dt><dd>{{ resolvedList(node, 'true_delays') }}</dd></div>
                              <div class="audit-truth-field--wide"><dt>各输入真实滞后</dt><dd>{{ resolvedMap(node, 'true_delays_by_input') }}</dd></div>
                              <div class="audit-truth-field--wide"><dt>AR 系数</dt><dd>{{ resolvedList(node, 'ar_coefficients') }}</dd></div>
                              <div class="audit-truth-field--wide"><dt>输入系数</dt><dd>{{ resolvedMap(node, 'input_coefficients') }}</dd></div>
                              <div class="audit-truth-field--wide"><dt>真实参数表</dt><dd>{{ resolvedMap(node, 'true_parameters') }}</dd></div>
                            </dl>
                          </section>

                          <section class="audit-subsection" data-audit-section="anomaly">
                            <h6>异常值注入</h6>
                            <div v-if="injectionData(node, 'anomaly_count_by_column', 'anomaly_rate_by_column').state === 'missing'" class="audit-empty">未记录</div>
                            <div v-else-if="injectionData(node, 'anomaly_count_by_column', 'anomaly_rate_by_column').state === 'empty'" class="audit-empty">未注入</div>
                            <div v-else class="audit-table-wrap">
                              <el-table class="audit-data-table anomaly-injection-table" :data="injectionData(node, 'anomaly_count_by_column', 'anomaly_rate_by_column').rows" stripe size="small">
                                <el-table-column prop="variable" label="变量" min-width="120" />
                                <el-table-column prop="count_label" label="注入数量" min-width="120" />
                                <el-table-column prop="rate_label" label="注入比例" min-width="120" />
                              </el-table>
                            </div>
                          </section>

                          <section class="audit-subsection" data-audit-section="missing">
                            <h6>缺失值注入</h6>
                            <div v-if="injectionData(node, 'missing_count_by_column', 'missing_rate_by_column').state === 'missing'" class="audit-empty">未记录</div>
                            <div v-else-if="injectionData(node, 'missing_count_by_column', 'missing_rate_by_column').state === 'empty'" class="audit-empty">未注入</div>
                            <div v-else class="audit-table-wrap">
                              <el-table class="audit-data-table missing-injection-table" :data="injectionData(node, 'missing_count_by_column', 'missing_rate_by_column').rows" stripe size="small">
                                <el-table-column prop="variable" label="变量" min-width="120" />
                                <el-table-column prop="count_label" label="注入数量" min-width="120" />
                                <el-table-column prop="rate_label" label="注入比例" min-width="120" />
                              </el-table>
                            </div>
                          </section>

                          <section class="audit-subsection" data-audit-section="freeze">
                            <h6>已知冻结注入</h6>
                            <div v-if="segmentData(node, 'freeze_segments').state === 'missing'" class="audit-empty">未记录</div>
                            <div v-else-if="segmentData(node, 'freeze_segments').state === 'empty'" class="audit-empty">未注入</div>
                            <div v-else class="audit-table-wrap">
                              <el-table class="audit-data-table freeze-injection-table" :data="segmentData(node, 'freeze_segments').rows" stripe size="small">
                                <el-table-column prop="variable" label="变量" min-width="120" />
                                <el-table-column prop="start_label" label="开始位置" min-width="120" />
                                <el-table-column prop="end_label" label="结束位置" min-width="120" />
                                <el-table-column prop="length_label" label="持续点数" min-width="120" />
                              </el-table>
                            </div>
                          </section>

                          <section class="audit-subsection" data-audit-section="drift">
                            <h6>已知漂移注入</h6>
                            <div v-if="segmentData(node, 'drift_segments').state === 'missing'" class="audit-empty">未记录</div>
                            <div v-else-if="segmentData(node, 'drift_segments').state === 'empty'" class="audit-empty">未注入</div>
                            <div v-else class="audit-table-wrap">
                              <el-table class="audit-data-table drift-injection-table" :data="segmentData(node, 'drift_segments').rows" stripe size="small">
                                <el-table-column prop="variable" label="变量" min-width="120" />
                                <el-table-column prop="start_label" label="开始位置" min-width="120" />
                                <el-table-column prop="end_label" label="结束位置" min-width="120" />
                                <el-table-column prop="length_label" label="持续点数" min-width="120" />
                              </el-table>
                            </div>
                          </section>

                          <section class="audit-subsection" data-audit-section="timestamps">
                            <h6>时间戳污染</h6>
                            <dl class="audit-list audit-basic-grid">
                              <div data-audit-field="irregular-timestamps"><dt>不规则时间戳</dt><dd>{{ resolvedCount(node, 'irregular_timestamp_count', '个') }}</dd></div>
                              <div><dt>重复时间戳</dt><dd>{{ resolvedCount(node, 'duplicate_timestamp_count', '个') }}</dd></div>
                            </dl>
                          </section>
                        </div>
                      </div>
                    </section>

                    <section
                      class="audit-evidence-card"
                      :class="{ 'is-expanded': isAuditEvidenceExpanded(`${node.id}-raw`) }"
                      data-audit-evidence="raw"
                    >
                      <button
                        type="button"
                        class="audit-evidence-card__trigger"
                        :aria-expanded="isAuditEvidenceExpanded(`${node.id}-raw`)"
                        :aria-controls="`audit-evidence-panel-${node.id}-raw`"
                        @click="toggleAuditEvidence(`${node.id}-raw`)"
                      >
                        <span class="audit-evidence-card__copy">
                          <span class="audit-evidence-card__title">原始审计参数</span>
                          <span class="audit-evidence-card__description">ProcessingRun / DatasetVersion 的原始审计记录</span>
                        </span>
                        <span class="audit-evidence-card__action">
                          {{ isAuditEvidenceExpanded(`${node.id}-raw`) ? '收起' : '查看详情' }}
                          <span class="audit-evidence-card__action-icon" aria-hidden="true">
                            {{ isAuditEvidenceExpanded(`${node.id}-raw`) ? '↑' : '→' }}
                          </span>
                        </span>
                      </button>
                      <div
                        v-show="isAuditEvidenceExpanded(`${node.id}-raw`)"
                        :id="`audit-evidence-panel-${node.id}-raw`"
                        class="audit-evidence-card__content audit-evidence-card__content--raw"
                        data-audit-evidence-panel="raw"
                      >
                        <div class="raw-audit-toolbar">
                          <span>完整原始字段和值，未经翻译或改写。</span>
                          <el-button size="small" plain @click="copyAuditJson(node)">复制 JSON</el-button>
                        </div>
                        <pre class="audit-json raw-audit-json">{{ formatAuditJson(node.parameters) }}</pre>
                      </div>
                    </section>
                  </div>
                </div>
              </el-card>
            </el-timeline-item>
          </el-timeline>
          <div v-else style="padding: 20px 0; text-align: center; color: var(--text-secondary)">
            暂无派生版本记录
          </div>
        </div>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, computed } from "vue";
import { useRoute, useRouter } from "vue-router";
import { DataLine, Share, ArrowRight, Opportunity } from "@element-plus/icons-vue";
import PageHeader from "../components/common/PageHeader.vue";
import StateView from "../components/StateView.vue";
import {
  getDatasetDetail,
  getDatasetProfile,
  getDatasetVersionPreview,
  getDatasetVersions,
} from "../api/datasets";
import type {
  DatasetItem,
  DatasetPreviewRow,
  DatasetProfile,
  DatasetVersionNode,
  DatasetVersionPreviewParams,
} from "../types/api";
import { ElMessage } from "element-plus";
import { useDatasetStore } from "../stores/datasetStore";

const route = useRoute();
const router = useRouter();
const datasetStore = useDatasetStore();
const activeTab = ref("overview");
const datasetId = (route.params.id as string) || "ds_s1";

const dataset = ref<DatasetItem | null>(null);
const detailLoading = ref(true);
const detailError = ref("");
const previewVersionId = ref("");
const previewPage = ref(1);
const previewPageSize = ref<DatasetVersionPreviewParams["page_size"]>(100);
const previewRows = ref<DatasetPreviewRow[]>([]);
const previewColumns = ref<string[]>([]);
const previewTotalItems = ref(0);
const previewTotalPages = ref(0);
const previewLoading = ref(false);
const previewError = ref("");
const profile = ref<DatasetProfile | null>(null);
const profileLoading = ref(false);
const versionNodes = ref<DatasetVersionNode[]>([]);
const expandedFreezePanels = ref<string[]>([]);
const expandedAuditEvidence = ref<string[]>([]);
const freezeSegmentDisplayLimit = 20;
let previewRequestGeneration = 0;

const previewRequestErrorMessage = (error: unknown) => {
  if (error && typeof error === "object") {
    const candidate = error as { code?: unknown; message?: unknown };
    const code = typeof candidate.code === "string" ? candidate.code : "ERR";
    const message = typeof candidate.message === "string" ? candidate.message : "未知错误";
    return `获取版本数据预览失败 [${code}]：${message}`;
  }
  return "获取版本数据预览失败 [ERR]：未知错误";
};

const fetchPreviewPage = async (
  requestedPage: number,
  requestedPageSize: DatasetVersionPreviewParams["page_size"]
) => {
  const versionId = previewVersionId.value;
  if (!versionId) return;
  const generation = ++previewRequestGeneration;
  previewLoading.value = true;
  previewError.value = "";
  try {
    const response = await getDatasetVersionPreview(datasetId, versionId, {
      page: requestedPage,
      page_size: requestedPageSize,
    });
    if (generation !== previewRequestGeneration) return;
    if (response.dataset_id !== datasetId || response.version_id !== versionId) {
      throw new Error("预览响应与当前数据集版本不一致");
    }
    previewRows.value = response.rows;
    previewColumns.value = response.columns;
    previewPage.value = response.page.page;
    previewPageSize.value = response.page.page_size;
    previewTotalItems.value = response.page.total;
    previewTotalPages.value = response.page.total_pages;
  } catch (error: unknown) {
    if (generation !== previewRequestGeneration) return;
    previewError.value = previewRequestErrorMessage(error);
    ElMessage.error(previewError.value);
  } finally {
    if (generation === previewRequestGeneration) {
      previewLoading.value = false;
    }
  }
};

const fetchDetail = async () => {
  previewRequestGeneration += 1;
  detailLoading.value = true;
  detailError.value = "";
  previewVersionId.value = "";
  previewPage.value = 1;
  previewPageSize.value = 100;
  previewRows.value = [];
  previewColumns.value = [];
  previewTotalItems.value = 0;
  previewTotalPages.value = 0;
  previewLoading.value = false;
  previewError.value = "";
  try {
    const res = await getDatasetDetail(datasetId);
    dataset.value = res;
    datasetStore.setActiveDataset(res);
    previewVersionId.value = res.version_id;
    await fetchPreviewPage(1, 100);
  } catch (err: any) {
    dataset.value = null;
    detailError.value = `获取数据集详情失败 [${err.code || 'ERR'}]：${err.message || '未知错误'}`;
    ElMessage.error(detailError.value);
  } finally {
    detailLoading.value = false;
  }
};

const fetchProfile = async () => {
  profileLoading.value = true;
  try {
    const res = await getDatasetProfile(datasetId);
    profile.value = res;
  } catch (err: any) {
    ElMessage.error(`获取数据质量 Profile 失败 [${err.code || 'ERR'}]: ${err.message}`);
  } finally {
    profileLoading.value = false;
  }
};

const fetchVersions = async () => {
  try {
    const res = await getDatasetVersions(datasetId);
    versionNodes.value = res.nodes || [];
  } catch (err: any) {
    // Keep empty array
    ElMessage.error(`获取版本历史失败 [${err.code || 'ERR'}]：${err.message || '未知错误'}`);
  }
};

const handlePreviewPageChange = (page: number) => {
  void fetchPreviewPage(page, previewPageSize.value);
};

const handlePreviewPageSizeChange = (pageSize: number) => {
  if (pageSize !== 50 && pageSize !== 100 && pageSize !== 200) return;
  void fetchPreviewPage(1, pageSize);
};

const formattedColStats = computed(() => {
  if (!profile.value || !profile.value.column_statistics) return [];
  return Object.entries(profile.value.column_statistics).map(([col, stat]) => ({
    col,
    count: stat.count,
    mean: stat.mean !== null ? stat.mean.toFixed(4) : "-",
    std: stat.std !== null ? stat.std.toFixed(4) : "-",
    min: stat.min !== null ? stat.min.toFixed(4) : "-",
    max: stat.max !== null ? stat.max.toFixed(4) : "-",
    q50: stat.q50 !== null ? stat.q50.toFixed(4) : "-",
  }));
});

const candidateFrozenSegments = computed(() => profile.value?.candidate_frozen_segments || []);
const previewRangeLabel = computed(() => {
  if (previewTotalItems.value === 0 || previewRows.value.length === 0) {
    return `第 0–0 行 / 共 ${previewTotalItems.value} 行`;
  }
  const start = (previewPage.value - 1) * previewPageSize.value + 1;
  const end = Math.min(start + previewRows.value.length - 1, previewTotalItems.value);
  return `第 ${start}–${end} 行 / 共 ${previewTotalItems.value} 行`;
});
const visibleCandidateFrozenSegments = computed(() =>
  candidateFrozenSegments.value.slice(0, freezeSegmentDisplayLimit)
);
const candidateFreezeSummary = computed(() => {
  const summary = profile.value?.freeze_detection_summary;
  const segments = candidateFrozenSegments.value;
  if (!summary || summary.candidate_count === 0 || !summary.longest_segment || segments.length === 0) {
    return "未检测到异常冻结段";
  }
  const longest = summary.longest_segment;
  return `候选异常冻结：共 ${summary.candidate_count} 段，涉及 ${summary.affected_column_count} 个变量；最长区段为 ${longest.column}，第${longest.start_index}–${longest.end_index}行，共${longest.length}点。`;
});

const formatPreviewValue = (value: unknown) => value === null || value === undefined ? "缺失" : String(value);
const shortIdentifier = (value?: string) => value ? `${value.slice(0, 8)}…` : "尚未生成";
const simulationValue = (value: unknown) =>
  value === null || value === undefined || value === "" ? "未记录" : String(value);
const simulationList = (value: unknown) =>
  Array.isArray(value) && value.length ? value.map(simulationValue).join(", ") : "未记录";
const simulationMap = (value: unknown) => {
  if (!value || typeof value !== "object" || Array.isArray(value)) return "未记录";
  const entries = Object.entries(value as Record<string, unknown>);
  return entries.length ? entries.map(([key, item]) => `${key}: ${simulationValue(item)}`).join("；") : "未记录";
};

const isAuditEvidenceExpanded = (panelId: string) => expandedAuditEvidence.value.includes(panelId);

const toggleAuditEvidence = (panelId: string) => {
  expandedAuditEvidence.value = isAuditEvidenceExpanded(panelId)
    ? expandedAuditEvidence.value.filter((item) => item !== panelId)
    : [...expandedAuditEvidence.value, panelId];
};

const formatDateTime = (value: string) => {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString("zh-CN");
};

const operationLabel = (tool: string) => ({
  raw_upload: "CSV 上传",
  simulation_generate: "仿真生成",
  "preprocessing.clean": "数据清洗",
  "preprocessing.lag_compensation": "时滞补偿",
  "preprocessing.feature_selection": "变量筛选",
}[tool] || tool);

const asRecord = (value: unknown): Record<string, unknown> =>
  value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};

type AuditDataState = "missing" | "empty" | "data";

type InjectionRow = {
  variable: string;
  count_label: string;
  rate_label: string;
};

type SegmentRow = {
  variable: string;
  start_label: string;
  end_label: string;
  length_label: string;
};

const CLEANING_ENUM_LABELS: Record<string, string> = {
  hampel: "Hampel 滤波",
  iqr: "IQR 四分位距",
  zscore: "Z-score 标准分数",
  z_score: "Z-score 标准分数",
  linear_interpolate: "线性插值替换",
  clip: "边界截断",
  none: "未启用",
  linear: "线性插值",
  ffill: "前向填充",
  forward_fill: "前向填充",
  bfill: "后向填充",
  backward_fill: "后向填充",
  mean: "均值聚合",
};

const ENUM_CLEANING_KEYS = new Set([
  "interpolation",
  "duplicate_strategy",
  "outlier_detector",
  "outlier_strategy",
  "smoothing",
]);

const cleaningEnumLabel = (value: string) =>
  CLEANING_ENUM_LABELS[value] || `${value}（未识别参数）`;

const hasOwn = (record: Record<string, unknown>, key: string) =>
  Object.prototype.hasOwnProperty.call(record, key);

const formatScalar = (value: unknown) => {
  if (value === null || value === undefined || value === "") return "未记录";
  return String(value);
};

const formatPercentage = (value: unknown) => {
  if (typeof value !== "number" || !Number.isFinite(value)) return "未记录";
  return `${(value * 100).toFixed(2)}%`;
};

const cleaningRawValue = (node: DatasetVersionNode, resolvedKey: string, requestKey?: string) => {
  const parameters = asRecord(node.parameters);
  const resolved = asRecord(parameters.resolved_parameters);
  const request = asRecord(parameters.request);
  return resolved[resolvedKey] ?? request[requestKey || resolvedKey];
};

const cleaningDisplay = (node: DatasetVersionNode, resolvedKey: string, requestKey?: string) => {
  const value = cleaningRawValue(node, resolvedKey, requestKey);
  if (value === null || value === undefined || value === "") return "未记录";
  if (resolvedKey === "resample_period_seconds") return `${String(value)} 秒`;
  if (resolvedKey === "hampel_window") return `${String(value)}个采样点`;
  if (ENUM_CLEANING_KEYS.has(resolvedKey) && typeof value === "string") {
    return cleaningEnumLabel(value);
  }
  return String(value);
};

const processingCount = (node: DatasetVersionNode, key: string, suffix = "个单元格") => {
  const processing = asRecord(node.audit_summary?.processing);
  const value = processing[key];
  return value === null || value === undefined ? "未记录" : `${String(value)}${suffix}`;
};

const legacyConstantCount = (node: DatasetVersionNode) =>
  node.audit_summary?.freeze?.historical_constant_value_segment_count ?? null;
const currentConstantCount = (node: DatasetVersionNode) => {
  const value = node.audit_summary?.freeze?.constant_value_segment_count;
  return value === undefined ? "未记录" : `${value}段`;
};
const candidateFreezeCount = (node: DatasetVersionNode) => {
  const value = node.audit_summary?.freeze?.candidate_frozen_segment_count;
  return value === undefined ? "未记录" : `${value}段`;
};

const LEGACY_DUPLICATE_WARNING = /^已按\s+\S+\s+规则处理\s+\d+\s*个重复时间戳。?$/;

const displayWarnings = (node: DatasetVersionNode) => {
  const warnings = node.audit_summary?.warnings || [];
  const processing = asRecord(node.audit_summary?.processing);
  const duplicateCount = processing.duplicate_timestamps_processed;
  const duplicateStrategy = cleaningRawValue(node, "duplicate_strategy");
  const formattedDuplicateWarning =
    typeof duplicateCount === "number" && duplicateCount > 0 && typeof duplicateStrategy === "string"
      ? `已采用${cleaningEnumLabel(duplicateStrategy)}处理${duplicateCount}行重复时间戳。`
      : null;
  let replacedLegacyWarning = false;
  const formattedWarnings = warnings.map((warning) => {
    if (formattedDuplicateWarning && LEGACY_DUPLICATE_WARNING.test(warning)) {
      replacedLegacyWarning = true;
      return formattedDuplicateWarning;
    }
    return warning;
  });
  if (formattedDuplicateWarning && !replacedLegacyWarning && !warnings.some((warning) => warning.includes("重复时间戳"))) {
    formattedWarnings.unshift(formattedDuplicateWarning);
  }
  return formattedWarnings;
};

const requestRecord = (node: DatasetVersionNode) => {
  const provenanceRequest = asRecord(node.provenance?.user_request);
  if (Object.keys(provenanceRequest).length > 0) return provenanceRequest;
  const parameters = asRecord(node.parameters);
  return asRecord(parameters.simulation_request);
};

const resolvedRecord = (node: DatasetVersionNode) => asRecord(node.provenance?.resolved_scenario_parameters);

const requestValue = (node: DatasetVersionNode, key: string, fallbackKey?: string, suffix = "") => {
  const request = requestRecord(node);
  const value = request[key] ?? (fallbackKey ? request[fallbackKey] : undefined);
  return value === null || value === undefined || value === "" ? "未记录" : `${String(value)}${suffix}`;
};

const requestRateValue = (node: DatasetVersionNode, key: string, zeroUsesScenarioDefault: boolean) => {
  const request = requestRecord(node);
  const value = request[key];
  if (value === null || value === undefined || value === "") return "未记录";
  if (value === 0 && zeroUsesScenarioDefault) return "使用场景默认值（原始请求值：0）";
  if (key === "noise_level") {
    return `${String(value)}（原始请求值；最终生效值见下方实际生效参数）`;
  }
  return typeof value === "number" ? formatPercentage(value) : String(value);
};

const resolvedScalar = (node: DatasetVersionNode, key: string) => {
  const resolved = resolvedRecord(node);
  return hasOwn(resolved, key) ? formatScalar(resolved[key]) : "未记录";
};

const resolvedList = (node: DatasetVersionNode, key: string) =>
  simulationList(resolvedRecord(node)[key]);

const resolvedMap = (node: DatasetVersionNode, key: string) =>
  simulationMap(resolvedRecord(node)[key]);

const resolvedCount = (node: DatasetVersionNode, key: string, suffix: string) => {
  const resolved = resolvedRecord(node);
  const value = resolved[key];
  if (!hasOwn(resolved, key) || value === null || value === undefined || value === "") return "未记录";
  return `${String(value)}${suffix}`;
};

const injectionData = (
  node: DatasetVersionNode,
  countKey: string,
  rateKey: string,
): { state: AuditDataState; rows: InjectionRow[] } => {
  const resolved = resolvedRecord(node);
  if (!hasOwn(resolved, countKey) && !hasOwn(resolved, rateKey)) return { state: "missing", rows: [] };
  const counts = asRecord(resolved[countKey]);
  const rates = asRecord(resolved[rateKey]);
  const variables = [...new Set([...Object.keys(counts), ...Object.keys(rates)])];
  if (variables.length === 0) return { state: "empty", rows: [] };
  return {
    state: "data",
    rows: variables.map((variable) => ({
      variable,
      count_label: hasOwn(counts, variable) ? `${formatScalar(counts[variable])}个` : "未记录",
      rate_label: hasOwn(rates, variable) ? formatPercentage(rates[variable]) : "未记录",
    })),
  };
};

const segmentData = (node: DatasetVersionNode, key: string): { state: AuditDataState; rows: SegmentRow[] } => {
  const resolved = resolvedRecord(node);
  if (!hasOwn(resolved, key) || !Array.isArray(resolved[key])) return { state: "missing", rows: [] };
  const segments = resolved[key] as unknown[];
  if (segments.length === 0) return { state: "empty", rows: [] };
  return {
    state: "data",
    rows: segments.map((segment) => {
      const item = asRecord(segment);
      const start = item.start_index ?? item.start_idx;
      const end = item.end_index ?? item.end_idx;
      const length = typeof start === "number" && typeof end === "number" ? end - start + 1 : null;
      return {
        variable: formatScalar(item.column ?? item.variable),
        start_label: formatScalar(start),
        end_label: formatScalar(end),
        length_label: length === null ? "未记录" : `${length}点`,
      };
    }),
  };
};

const formatAuditJson = (value: unknown) => JSON.stringify(value === undefined ? {} : value, null, 2);

const copyAuditJson = async (node: DatasetVersionNode) => {
  try {
    if (!navigator.clipboard?.writeText) throw new Error("Clipboard API unavailable");
    await navigator.clipboard.writeText(formatAuditJson(node.parameters));
    ElMessage.success("原始审计 JSON 已复制");
  } catch {
    ElMessage.error("复制失败，请手动选择原始审计 JSON");
  }
};

const openCleaning = () => {
  if (!dataset.value) return;
  datasetStore.setActiveDataset(dataset.value);
  const versionId = dataset.value.version_id || dataset.value.latest_version_id;
  router.push({
    name: "Cleaning",
    query: { dataset_id: dataset.value.id, version_id: versionId },
  });
};

onMounted(() => {
  fetchDetail();
  fetchProfile();
  fetchVersions();
});
</script>

<style scoped>
.dataset-detail-view {
  display: flex;
  flex-direction: column;
  min-height: 100%;
  min-width: 0;
}

.page-header {
  flex: 0 0 auto;
}

.detail-tabs {
  display: flex;
  flex: 0 0 auto;
  flex-direction: column;
  min-width: 0;
}

.detail-tabs :deep(.el-tabs__header) {
  flex: 0 0 auto;
}

.detail-tabs :deep(.el-tabs__content) {
  flex: 0 0 auto;
  min-width: 0;
  overflow: visible;
}

.preview-tab-content {
  min-width: 0;
}
.preview-card {
  min-width: 0;
  margin-bottom: 0;
}

.simulation-overview-card {
  margin-bottom: 16px;
}

.simulation-overview-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 10px 18px;
  margin: 0;
}

.simulation-overview-grid > div {
  min-width: 0;
  padding: 10px 0;
  border-bottom: 1px solid var(--border-light);
}

.simulation-overview-grid dt {
  color: var(--text-secondary);
  font-size: 12px;
}

.simulation-overview-grid dd {
  margin: 3px 0 0;
  overflow-wrap: anywhere;
  color: var(--text-primary);
  font-weight: 600;
}

.simulation-missing-note {
  margin: 12px 0 0;
  color: var(--text-secondary);
}

.preview-card .industrial-card-header {
  flex: 0 0 auto;
  gap: 12px;
  min-width: 0;
}

.preview-table-region {
  min-width: 0;
}

.preview-table {
  width: 100%;
}

.preview-empty,
.preview-state {
  display: grid;
  place-items: center;
}

.preview-empty {
  padding: 20px 0;
  color: var(--text-secondary);
}

.preview-page-error {
  margin-bottom: 16px;
}

.preview-pagination-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  padding-top: 18px;
}

.preview-page-range {
  color: var(--text-secondary);
  font-size: 13px;
  font-weight: 500;
  white-space: nowrap;
}

@media (max-width: 720px) {
  .preview-pagination-bar {
    align-items: flex-start;
    flex-direction: column;
  }
}
.page-header {
  margin-bottom: 20px;
}

.subtitle {
  font-size: 13px;
  color: var(--text-secondary);
  margin-top: 4px;
}

.version-id-help {
  margin-left: 6px;
  color: var(--color-primary);
  cursor: help;
  font-size: 12px;
  text-decoration: underline dotted;
  text-underline-offset: 3px;
}

.profile-score-box {
  display: flex;
  align-items: center;
  gap: 24px;
}

.score-num {
  font-size: 42px;
  font-weight: 800;
  color: var(--color-success);
  font-family: var(--font-sans);
  letter-spacing: normal;
}

.score-num.warning {
  color: var(--color-warning-dark);
}

.max {
  font-size: 16px;
  color: var(--text-secondary);
  font-weight: 400;
}

.score-desc .title {
  font-size: 18px;
  font-weight: 600;
  color: var(--text-primary);
}

.freeze-segments {
  margin-bottom: 20px;
  padding: 14px;
  border: 1px solid var(--border-light);
  border-radius: 6px;
  background: var(--bg-subtle);
}

.preview-error {
  display: grid;
  gap: 16px;
  justify-items: start;
}

.preview-null {
  color: var(--text-secondary);
  font-style: italic;
}

.version-card,
.audit-break,
.audit-json {
  min-width: 0;
  overflow-wrap: anywhere;
  word-break: break-word;
}

.version-card h4 {
  margin: 0 0 14px;
}

.version-basics,
.audit-list {
  margin: 0;
}

.version-basics > div,
.audit-list > div {
  display: grid;
  grid-template-columns: minmax(120px, 180px) minmax(0, 1fr);
  gap: 12px;
  padding: 6px 0;
  border-bottom: 1px solid var(--border-light);
}

.version-basics dt,
.audit-list dt {
  color: var(--text-secondary);
}

.version-basics dd,
.audit-list dd {
  margin: 0;
}

.audit-groups {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: 12px;
  margin-top: 16px;
}

.audit-group {
  padding: 12px;
  border: 1px solid var(--border-light);
  border-radius: 6px;
  background: var(--bg-subtle);
}

.audit-group h5 {
  margin: 0 0 8px;
}

.audit-warnings {
  margin: 10px 0 0;
  padding-left: 20px;
  color: var(--color-warning-dark);
}

.audit-json {
  max-width: 100%;
  max-height: 320px;
  margin: 0;
  padding: 12px;
  overflow: auto;
  white-space: pre;
  background: var(--bg-subtle);
  border: 1px solid var(--border-light);
  border-radius: 4px;
  font-family: var(--font-mono);
  font-size: 12px;
  line-height: 1.6;
}

.simulation-audit-groups .provenance-summary {
  grid-column: 1 / -1;
}

.audit-evidence-chain {
  display: grid;
  gap: 10px;
  margin-top: 14px;
}

.audit-evidence-card {
  min-width: 0;
  background: var(--surface-1);
  border: 1px solid var(--border-default);
  border-radius: 6px;
  transition:
    background-color 180ms ease,
    border-color 180ms ease,
    transform 180ms ease;
}

.audit-evidence-card:hover {
  background: var(--accent-soft);
  border-color: var(--accent-border);
  transform: translateY(-1px);
}

.audit-evidence-card.is-expanded {
  border-color: var(--accent-border);
}

.audit-evidence-card__trigger {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 14px;
  align-items: center;
  width: 100%;
  padding: 14px 16px;
  color: var(--text-primary);
  font-family: var(--font-sans);
  text-align: left;
  cursor: pointer;
  background: transparent;
  border: 0;
  border-radius: 6px;
}

.audit-evidence-card__trigger:focus-visible {
  outline: 2px solid var(--border-focus);
  outline-offset: 2px;
}

.audit-evidence-card__copy {
  display: grid;
  gap: 3px;
  min-width: 0;
}

.audit-evidence-card__title {
  font-size: 14px;
  font-weight: 600;
  line-height: 1.4;
}

.audit-evidence-card__description {
  color: var(--text-secondary);
  font-size: 12px;
  font-weight: 400;
  line-height: 1.5;
}

.audit-evidence-card__action {
  display: inline-flex;
  gap: 5px;
  align-items: center;
  color: var(--accent-dark);
  font-size: 12px;
  font-weight: 600;
  white-space: nowrap;
}

.audit-evidence-card__action-icon {
  display: inline-block;
  transition: transform 180ms ease;
}

.audit-evidence-card:hover:not(.is-expanded) .audit-evidence-card__action-icon {
  transform: translateX(3px);
}

.audit-evidence-card.is-expanded:hover .audit-evidence-card__action-icon {
  transform: translateY(-2px);
}

.audit-evidence-card__content {
  margin: 0 16px;
  padding: 0 0 16px;
  border-top: 1px solid var(--border-subtle);
}

.audit-evidence-card__content--raw {
  padding-top: 14px;
}

.audit-structured {
  min-width: 0;
  padding: 12px 4px 4px;
}

.audit-section-title,
.audit-subsection h6 {
  margin: 0 0 8px;
  color: var(--text-primary);
  font-size: 14px;
  font-weight: 600;
}

.audit-section-note {
  margin: 0 0 12px;
  color: var(--text-secondary);
  font-size: 13px;
  line-height: 1.6;
}

.resolved-parameters-view {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.resolved-parameters-view > .audit-section-title {
  grid-column: 1 / -1;
}

.resolved-parameters-view [data-audit-section='basic'],
.resolved-parameters-view [data-audit-section='truth'],
.resolved-parameters-view [data-audit-section='timestamps'] {
  grid-column: 1 / -1;
}

.audit-subsection {
  min-width: 0;
  padding: 12px;
  border: 1px solid var(--border-light);
  border-radius: 6px;
  background: var(--bg-subtle);
}

.audit-basic-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 0 12px;
}

.audit-truth-grid {
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
}

.audit-list > .audit-truth-field--wide {
  grid-column: 1 / -1;
  grid-template-columns: minmax(120px, 180px) minmax(0, 1fr);
}

.audit-truth-field--wide dd {
  min-width: 0;
  overflow-x: auto;
  overflow-wrap: normal;
  word-break: normal;
}

.audit-table-wrap {
  min-width: 0;
  overflow-x: auto;
}

.audit-data-table {
  min-width: 460px;
}

.audit-empty {
  padding: 14px;
  color: var(--text-secondary);
  text-align: center;
  background: var(--bg-surface);
  border: 1px dashed var(--border-light);
  border-radius: 4px;
}

.raw-audit-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 10px;
  color: var(--text-secondary);
  font-size: 13px;
}

.raw-audit-toolbar .el-button {
  flex: 0 0 auto;
  white-space: nowrap;
}

@media (max-width: 980px) {
  .resolved-parameters-view {
    grid-template-columns: minmax(0, 1fr);
  }

  .resolved-parameters-view > .audit-section-title {
    grid-column: auto;
  }

  .resolved-parameters-view [data-audit-section='basic'],
  .resolved-parameters-view [data-audit-section='truth'],
  .resolved-parameters-view [data-audit-section='timestamps'] {
    grid-column: auto;
  }
}
@media (max-width: 720px) {
  .audit-truth-grid {
    grid-template-columns: minmax(0, 1fr);
  }

  .version-basics > div,
  .audit-list > div {
    grid-template-columns: 1fr;
    gap: 2px;
  }

  .audit-list > .audit-truth-field--wide {
    grid-template-columns: 1fr;
  }

  .audit-evidence-card__trigger {
    grid-template-columns: minmax(0, 1fr);
    gap: 10px 12px;
  }

  .audit-evidence-card__action {
    grid-column: 1;
    justify-self: start;
  }

  .raw-audit-toolbar {
    align-items: flex-start;
    flex-direction: column;
  }
}

.freeze-segments h4 {
  margin: 0 0 6px;
  color: var(--text-primary);
}

.freeze-hint,
.freeze-limit-note {
  margin: 0 0 10px;
  color: var(--text-secondary);
  font-size: 13px;
  line-height: 1.6;
}

.freeze-limit-note {
  margin: 10px 0 0;
}

.stat-mini-card {
  background: var(--bg-subtle);
  border: 1px solid var(--border-light);
  border-radius: 6px;
  padding: 10px;
  text-align: center;
}

.col-name {
  font-weight: 600;
  font-size: 13px;

  color: var(--text-primary);
}

.rate-val {
  font-size: 18px;
  font-weight: 700;
  color: var(--color-primary);
  font-family: var(--font-sans);
  letter-spacing: normal;
  margin: 4px 0;
}

.sub-info {
  font-size: 11px;
  color: var(--text-muted);
}

.recommendations h4 {
  margin-bottom: 8px;
  color: var(--text-primary);
}

.recommendations ul {
  padding-left: 20px;
  color: var(--text-secondary);
  font-size: 14px;
  line-height: 1.8;
}
</style>
