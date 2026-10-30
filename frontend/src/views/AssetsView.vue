<template>
  <div class="page-container assets-view">
    <PageHeader
      title="功能中心"
      description="集中访问从数据准备、预处理、系统辨识到分析交付的工业时序建模能力。"
    />

    <!-- Quick navigation cards -->
    <div class="assets-grid">
      <router-link to="/datasets" class="asset-card">
        <div class="asset-card__icon">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
            <ellipse cx="12" cy="5" rx="9" ry="3"/>
            <path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/>
            <path d="M3 12c0 1.66 4 3 9 3s9-1.34 9-3"/>
          </svg>
        </div>
        <div class="asset-card__body">
          <div class="asset-card__title">数据集与版本</div>
          <div class="asset-card__desc">管理工业时序数据、字段角色与处理版本血缘</div>
        </div>
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16" stroke-linecap="round" stroke-linejoin="round" class="card-arrow"><path d="m9 18 6-6-6-6"/></svg>
      </router-link>

      <router-link to="/assets/preprocessing" class="asset-card">
        <div class="asset-card__icon">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
            <line x1="4" x2="20" y1="6" y2="6"/><circle cx="9" cy="6" r="2"/><line x1="4" x2="20" y1="12" y2="12"/><circle cx="15" cy="12" r="2"/><line x1="4" x2="20" y1="18" y2="18"/><circle cx="11" cy="18" r="2"/>
          </svg>
        </div>
        <div class="asset-card__body">
          <div class="asset-card__title">预处理与优选</div>
          <div class="asset-card__desc">完成清洗、动态区段筛选、时滞补偿与共线性处理</div>
        </div>
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16" stroke-linecap="round" stroke-linejoin="round" class="card-arrow"><path d="m9 18 6-6-6-6"/></svg>
      </router-link>

      <router-link to="/assets/modeling" class="asset-card">
        <div class="asset-card__icon">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
            <polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/>
          </svg>
        </div>
        <div class="asset-card__body">
          <div class="asset-card__title">建模与寻优</div>
          <div class="asset-card__desc">执行系统辨识、模型评价与闭环参数寻优</div>
        </div>
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16" stroke-linecap="round" stroke-linejoin="round" class="card-arrow"><path d="m9 18 6-6-6-6"/></svg>
      </router-link>

      <router-link to="/simulation" class="asset-card">
        <div class="asset-card__icon">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
            <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>
          </svg>
        </div>
        <div class="asset-card__body">
          <div class="asset-card__title">仿真测试集生成</div>
          <div class="asset-card__desc">生成带明确真值的 S1–S6 工业时序测试数据</div>
        </div>
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16" stroke-linecap="round" stroke-linejoin="round" class="card-arrow"><path d="m9 18 6-6-6-6"/></svg>
      </router-link>

      <router-link to="/assets/delivery" class="asset-card">
        <div class="asset-card__icon">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" x2="8" y1="13" y2="13"/><line x1="16" x2="8" y1="17" y2="17"/>
          </svg>
        </div>
        <div class="asset-card__body">
          <div class="asset-card__title">分析与交付</div>
          <div class="asset-card__desc">完成消融评测、工程报告与优选数据交付</div>
        </div>
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16" stroke-linecap="round" stroke-linejoin="round" class="card-arrow"><path d="m9 18 6-6-6-6"/></svg>
      </router-link>

      <router-link to="/settings" class="asset-card">
        <div class="asset-card__icon">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .34 1.88l.06.06-2.83 2.83-.06-.06A1.7 1.7 0 0 0 15 19.4a1.7 1.7 0 0 0-1 .6 1.7 1.7 0 0 0-.4 1.1V21h-4v-.09A1.7 1.7 0 0 0 8.6 19.4a1.7 1.7 0 0 0-1.88.34l-.06.06-2.83-2.83.06-.06A1.7 1.7 0 0 0 4.6 15a1.7 1.7 0 0 0-.6-1 1.7 1.7 0 0 0-1.1-.4H3v-4h.09A1.7 1.7 0 0 0 4.6 8.6a1.7 1.7 0 0 0-.34-1.88l-.06-.06 2.83-2.83.06.06A1.7 1.7 0 0 0 9 4.6a1.7 1.7 0 0 0 1-.6 1.7 1.7 0 0 0 .4-1.1V3h4v.09A1.7 1.7 0 0 0 15.4 4.6a1.7 1.7 0 0 0 1.88-.34l.06-.06 2.83 2.83-.06.06A1.7 1.7 0 0 0 19.4 9c.24.36.45.67.6 1 .14.35.22.72.22 1.1V11h.78v4h-.09a1.7 1.7 0 0 0-1.51 0z"/>
          </svg>
        </div>
        <div class="asset-card__body">
          <div class="asset-card__title">系统环境设置</div>
          <div class="asset-card__desc">配置模型服务、运行环境与系统参数</div>
        </div>
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16" stroke-linecap="round" stroke-linejoin="round" class="card-arrow"><path d="m9 18 6-6-6-6"/></svg>
      </router-link>
    </div>
  </div>
</template>

<script setup lang="ts">
import PageHeader from '../components/common/PageHeader.vue';
</script>

<style scoped>
.assets-view {
  min-height: 100%;
}

.assets-view :deep(.page-header-unified__desc) {
  max-width: 860px;
  font-family: var(--font-sans);
  font-size: 16px;
  font-weight: 400;
  line-height: 1.6;
  color: var(--text-secondary);
}

.assets-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 16px;
}

.asset-card {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 18px 20px;
  background: #FFFFFF;
  border: 1px solid #E8EAE5;
  border-radius: 10px;
  color: inherit;
  text-decoration: none;
  transition: background-color 180ms ease, border-color 180ms ease, box-shadow 180ms ease, transform 180ms ease;
}

.asset-card:hover {
  background: #F7F9F5;
  border-color: #D6DDD2;
  transform: translateY(-1px);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.04);
}

.asset-card:focus-visible {
  outline: 2px solid var(--border-focus, #82A978);
  outline-offset: 2px;
}

.asset-card__icon {
  width: 42px;
  height: 42px;
  border-radius: 8px;
  background: #F0F4EE;
  border: 1px solid #DFE6DC;
  color: #5E8358;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  transition: background-color 180ms ease, color 180ms ease;
}

.asset-card:hover .asset-card__icon {
  background: #E8F0E5;
  color: #426340;
}

.asset-card__icon svg {
  width: 20px;
  height: 20px;
}

.asset-card__body {
  flex: 1;
  min-width: 0;
}

.asset-card__title {
  font-family: var(--font-sans);
  font-size: 16px;
  font-weight: 600;
  color: #2C332B;
  letter-spacing: normal;
  margin-bottom: 4px;
}

.asset-card:hover .asset-card__title {
  color: #426340;
}

.asset-card__desc {
  min-height: 43px;
  font-family: var(--font-sans);
  font-size: 14px;
  color: #747A72;
  line-height: 1.55;
}

.card-arrow {
  color: #A0A69D;
  transition: transform 180ms ease, color 180ms ease;
  flex-shrink: 0;
}

.asset-card:hover .card-arrow {
  color: #426340;
  transform: translateX(2px);
}

@media (max-width: 1180px) {
  .assets-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 720px) {
  .assets-grid {
    grid-template-columns: 1fr;
  }
}
</style>
