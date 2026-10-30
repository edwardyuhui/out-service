import { test } from '@playwright/test';
import * as path from 'node:path';
import * as fs from 'node:fs';

const artifactDir = path.resolve(process.cwd(), '../artifacts/layout-refactor');

test.beforeAll(() => {
  if (!fs.existsSync(artifactDir)) {
    fs.mkdirSync(artifactDir, { recursive: true });
  }
});

test.describe('Layout Spatial Visual QA', () => {
  test('Capture Home & Workspace at 1920x1080 and 1440x900', async ({ page }) => {
    // bypass landing gate by setting localStorage
    await page.addInitScript(() => {
      localStorage.setItem('indusopt_landing_visited', 'true');
    });

    // 1. Home - 1920x1080
    await page.setViewportSize({ width: 1920, height: 1080 });
    await page.goto('/home');
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(500);
    await page.screenshot({ path: path.join(artifactDir, 'home-1920x1080.png'), fullPage: false });

    // 2. Home - 1440x900
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto('/home');
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(500);
    await page.screenshot({ path: path.join(artifactDir, 'home-1440x900.png'), fullPage: false });

    // 3. Workspace - 1920x1080
    await page.setViewportSize({ width: 1920, height: 1080 });
    await page.goto('/workspace');
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(500);
    await page.screenshot({ path: path.join(artifactDir, 'workspace-1920x1080.png'), fullPage: false });

    // 4. Workspace - 1440x900
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto('/workspace');
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(500);
    await page.screenshot({ path: path.join(artifactDir, 'workspace-1440x900.png'), fullPage: false });

    // 5. Datasets - 1440x900
    await page.goto('/datasets');
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(500);
    await page.screenshot({ path: path.join(artifactDir, 'datasets-1440x900.png'), fullPage: false });

    // 6. ARX Modeling - 1440x900
    await page.goto('/modeling/arx');
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(500);
    await page.screenshot({ path: path.join(artifactDir, 'arx-1440x900.png'), fullPage: false });

    // 7. Optimization - 1440x900
    await page.goto('/modeling/optimization');
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(500);
    await page.screenshot({ path: path.join(artifactDir, 'optimization-1440x900.png'), fullPage: false });

    // 8. Deliverables - 1440x900
    await page.goto('/deliverables');
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(500);
    await page.screenshot({ path: path.join(artifactDir, 'deliverables-1440x900.png'), fullPage: false });
  });
});
