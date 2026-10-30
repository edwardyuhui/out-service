<template>
  <div class="default-layout">
    <AppHeader @open-command="openCmdPalette" />

    <div class="layout-body">
      <AppSidebar />

      <main
        ref="mainScroller"
        class="layout-main"
        data-main-scroller
        @wheel.passive="handleBoundaryWheel"
        @touchstart.passive="handleTouchStart"
        @touchmove.passive="handleTouchMove"
        @touchend.passive="handleTouchEnd"
        @touchcancel.passive="handleTouchEnd"
      >
        <div
          class="route-stage"
          data-scroll-stage
          :class="{ 'is-rebounding': isRebounding }"
          :style="{ transform: `translate3d(0, ${bounceOffset}px, 0)` }"
        >
          <router-view />
        </div>
      </main>
    </div>

    <!-- Global Command Palette -->
    <CommandPalette ref="cmdPaletteRef" />
  </div>
</template>

<script setup lang="ts">
import { onBeforeUnmount, ref } from "vue";
import AppHeader from "../components/AppHeader.vue";
import AppSidebar from "../components/AppSidebar.vue";
import CommandPalette from "../components/CommandPalette.vue";

const mainScroller = ref<HTMLElement | null>(null);
const cmdPaletteRef = ref<{ open: () => void; close: () => void } | null>(null);
const bounceOffset = ref(0);
const isRebounding = ref(false);
let settleTimer: ReturnType<typeof setTimeout> | null = null;
let reboundTimer: ReturnType<typeof setTimeout> | null = null;
let touchStartY: number | null = null;

function openCmdPalette() {
  cmdPaletteRef.value?.open();
}

const prefersReducedMotion = () =>
  typeof window !== "undefined" &&
  typeof window.matchMedia === "function" &&
  window.matchMedia("(prefers-reduced-motion: reduce)").matches;

const clearBounceTimers = () => {
  if (settleTimer !== null) clearTimeout(settleTimer);
  if (reboundTimer !== null) clearTimeout(reboundTimer);
};

const settleBounce = () => {
  isRebounding.value = true;
  bounceOffset.value = 0;
  reboundTimer = setTimeout(() => {
    isRebounding.value = false;
  }, 320);
};

const handleBoundaryWheel = (event: WheelEvent) => {
  const scroller = mainScroller.value;
  if (!scroller || prefersReducedMotion()) return;

  const atTop = scroller.scrollTop <= 0;
  const atBottom = scroller.scrollTop + scroller.clientHeight >= scroller.scrollHeight - 1;
  const pullingPastTop = atTop && event.deltaY < 0;
  const pullingPastBottom = atBottom && event.deltaY > 0;
  if (!pullingPastTop && !pullingPastBottom) return;

  clearBounceTimers();
  isRebounding.value = false;
  const direction = pullingPastTop ? 1 : -1;
  const distance = Math.min(14, 4 + Math.abs(event.deltaY) * 0.08);
  bounceOffset.value = direction * distance;
  settleTimer = setTimeout(settleBounce, 55);
};

const handleTouchStart = (event: TouchEvent) => {
  touchStartY = event.touches[0]?.clientY ?? null;
};

const handleTouchMove = (event: TouchEvent) => {
  const scroller = mainScroller.value;
  const currentY = event.touches[0]?.clientY;
  if (!scroller || touchStartY === null || currentY === undefined || prefersReducedMotion()) return;

  const dragDistance = currentY - touchStartY;
  const atTop = scroller.scrollTop <= 0;
  const atBottom = scroller.scrollTop + scroller.clientHeight >= scroller.scrollHeight - 1;
  const pullingPastTop = atTop && dragDistance > 0;
  const pullingPastBottom = atBottom && dragDistance < 0;
  if (!pullingPastTop && !pullingPastBottom) return;

  clearBounceTimers();
  isRebounding.value = false;
  bounceOffset.value = Math.sign(dragDistance) * Math.min(14, Math.abs(dragDistance) * 0.12);
};

const handleTouchEnd = () => {
  touchStartY = null;
  if (bounceOffset.value !== 0) settleBounce();
};

onBeforeUnmount(clearBounceTimers);
</script>

<style scoped>
.default-layout {
  display: flex;
  flex-direction: column;
  height: 100vh;
  width: 100vw;
  overflow: hidden;
}

.layout-body {
  display: flex;
  flex: 1;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
}

.layout-main {
  position: relative;
  flex: 1;
  min-width: 0;
  min-height: 0;
  padding: 24px clamp(20px, 3vw, 36px);
  overflow-y: auto;
  overscroll-behavior-y: contain;
  background-color: var(--bg-app);
}

.layout-main::before {
  position: absolute;
  inset: 0;
  pointer-events: none;
  content: "";
  background-image:
    linear-gradient(var(--workspace-grid) 1px, transparent 1px),
    linear-gradient(90deg, var(--workspace-grid) 1px, transparent 1px);
  background-size: 40px 40px;
  opacity: 0.5;
  z-index: 0;
}

.route-stage {
  position: relative;
  z-index: 1;
  min-height: 100%;
  transition: transform 70ms ease-out;
  will-change: transform;
}

.route-stage.is-rebounding {
  transition: transform 320ms cubic-bezier(0.2, 0.9, 0.25, 1.25);
}

@media (prefers-reduced-motion: reduce) {
  .route-stage {
    transition: none;
    will-change: auto;
  }
}
</style>
