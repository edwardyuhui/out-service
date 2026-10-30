<template>
  <header class="landing-header">
    <a class="landing-brand" href="#landing-top" aria-label="IndusOpt 工模智优首页">
      <span class="landing-brand-mark" aria-hidden="true">
        <span></span>
        <span></span>
        <span></span>
      </span>
      <span class="brand-title">IndusOpt 工模智优</span>
      <span class="brand-tag font-mono">A14</span>
    </a>

    <!-- Desktop Navigation -->
    <nav class="landing-nav" aria-label="Landing 页面导航">
      <a href="#landing-top">实时沙盘</a>
      <a href="#ablation-benchmark">实测对账</a>
      <a href="#pipeline-architecture">工程闭环</a>
      <a href="#trusted-engineering">数据血缘</a>
    </nav>

    <!-- Right Actions -->
    <div class="header-right-actions">
      <!-- Mobile Menu Toggle Button -->
      <button
        class="mobile-menu-btn"
        type="button"
        :aria-expanded="mobileMenuOpen"
        aria-label="切换目录导航"
        @click="mobileMenuOpen = !mobileMenuOpen"
      >
        <svg class="menu-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <line x1="3" y1="12" x2="21" y2="12"></line>
          <line x1="3" y1="6" x2="21" y2="6"></line>
          <line x1="3" y1="18" x2="21" y2="18"></line>
        </svg>
        <span>目录</span>
      </button>

      <button class="landing-header-cta" type="button" @click="emit('explore')">
        进入工作台
        <span aria-hidden="true">→</span>
      </button>
    </div>

    <!-- Lightweight Mobile Drawer Popup -->
    <div v-if="mobileMenuOpen" class="mobile-drawer" @click="mobileMenuOpen = false">
      <div class="mobile-drawer-content" @click.stop>
        <div class="drawer-header">
          <span class="drawer-title font-mono">PAGE NAVIGATION</span>
          <button class="drawer-close" type="button" @click="mobileMenuOpen = false">✕</button>
        </div>
        <nav class="mobile-nav-links">
          <a href="#landing-top" @click="mobileMenuOpen = false">实时沙盘</a>
          <a href="#ablation-benchmark" @click="mobileMenuOpen = false">实测对账</a>
          <a href="#pipeline-architecture" @click="mobileMenuOpen = false">工程闭环</a>
          <a href="#trusted-engineering" @click="mobileMenuOpen = false">数据血缘</a>
        </nav>
      </div>
    </div>
  </header>
</template>

<script setup lang="ts">
import { ref } from "vue";

const emit = defineEmits<{
  explore: [];
}>();

const mobileMenuOpen = ref(false);
</script>

<style scoped>
.landing-header {
  position: sticky;
  top: 0;
  z-index: 50;
  display: grid;
  grid-template-columns: minmax(240px, 1fr) auto minmax(240px, 1fr);
  align-items: center;
  width: 100%;
  height: 64px;
  margin: 0 auto;
  padding: 0 max(22px, calc((100vw - 1380px) / 2));
  border-bottom: 1px solid var(--landing-border);
  background: var(--landing-header-bg);
  backdrop-filter: blur(14px);
  -webkit-backdrop-filter: blur(14px);
}

.landing-brand,
.landing-nav a {
  color: var(--landing-text);
  text-decoration: none;
}

.landing-brand {
  display: inline-flex;
  align-items: center;
  justify-self: start;
  gap: 10px;
  font-size: 15px;
  font-weight: 700;
  letter-spacing: -0.01em;
}

.brand-title {
  white-space: nowrap;
}

.brand-tag {
  font-size: 10px;
  padding: 1px 5px;
  border-radius: 3px;
  background: var(--landing-accent-soft);
  color: var(--landing-accent);
  border: 1px solid var(--landing-border-active);
}

.landing-brand-mark {
  display: grid;
  grid-template-columns: repeat(3, 3.5px);
  align-items: end;
  gap: 2.5px;
  width: 16px;
  height: 16px;
}

.landing-brand-mark span {
  display: block;
  background: var(--landing-accent);
  border-radius: 1px;
}

.landing-brand-mark span:nth-child(1) {
  height: 7px;
}

.landing-brand-mark span:nth-child(2) {
  height: 16px;
}

.landing-brand-mark span:nth-child(3) {
  height: 11px;
}

.landing-nav {
  display: flex;
  align-items: center;
  gap: clamp(18px, 2.5vw, 36px);
  white-space: nowrap;
}

.landing-nav a {
  position: relative;
  padding: 6px 0;
  color: var(--landing-muted);
  font-size: 13px;
  font-weight: 500;
  transition: color 0.2s ease;
}

.landing-nav a::after {
  position: absolute;
  right: 0;
  bottom: 0;
  left: 0;
  height: 2px;
  background: var(--landing-accent);
  content: "";
  opacity: 0;
  transform: scaleX(0.3);
  transition: all 0.2s ease;
}

.landing-nav a:hover,
.landing-nav a:focus-visible {
  color: var(--landing-text);
}

.landing-nav a:hover::after,
.landing-nav a:focus-visible::after {
  opacity: 1;
  transform: scaleX(1);
}

.header-right-actions {
  justify-self: end;
  display: flex;
  align-items: center;
  gap: 10px;
}

.mobile-menu-btn {
  display: none;
  align-items: center;
  gap: 4px;
  padding: 6px 10px;
  border: 1px solid var(--landing-border);
  background: #ffffff;
  color: var(--landing-text);
  border-radius: 6px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
}

.menu-svg {
  width: 14px;
  height: 14px;
}

.landing-header-cta {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-height: 36px;
  padding: 0 16px;
  border: 1px solid var(--landing-accent);
  border-radius: var(--landing-radius);
  background: var(--landing-accent);
  color: var(--landing-accent-contrast);
  cursor: pointer;
  font-size: 13px;
  font-weight: 700;
  white-space: nowrap;
  transition: all 0.2s ease;
}

.landing-header-cta:hover {
  border-color: var(--landing-accent-strong);
  background: var(--landing-accent-strong);
}

/* Mobile Drawer */
.mobile-drawer {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.4);
  backdrop-filter: blur(4px);
  z-index: 100;
  display: flex;
  flex-direction: column;
  justify-content: flex-start;
  padding: 16px;
}

.mobile-drawer-content {
  background: #ffffff;
  border-radius: 12px;
  padding: 20px;
  box-shadow: 0 20px 48px rgba(0, 0, 0, 0.15);
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.drawer-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding-bottom: 10px;
  border-bottom: 1px solid #e2e8f0;
}

.drawer-title {
  font-size: 10px;
  font-weight: 700;
  color: #64748b;
  letter-spacing: 0.08em;
}

.drawer-close {
  background: transparent;
  border: none;
  font-size: 16px;
  color: #64748b;
  cursor: pointer;
}

.mobile-nav-links {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.mobile-nav-links a {
  font-size: 15px;
  font-weight: 600;
  color: #0f172a;
  text-decoration: none;
  padding: 6px 0;
  border-bottom: 1px solid #f1f5f9;
}

.font-mono {
  font-family: var(--font-mono);
}

@media (max-width: 860px) {
  .landing-header {
    grid-template-columns: 1fr auto;
  }
  .landing-nav {
    display: none;
  }
  .mobile-menu-btn {
    display: inline-flex;
  }
}
</style>
