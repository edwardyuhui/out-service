import { expect, test } from '@playwright/test';

test('时滞补偿：批准后显示真实进度、补偿成果并可下载，刷新后仍可见', async ({ page, request }) => {
  const generated = await request.post('/api/v1/simulation/generate', {
    data: { scenario: 'S1', n_steps: 900, input_count: 1, seed: 81, name: 'confirmation-regression' },
  });
  expect(generated.status()).toBe(201);
  const dataset = (await generated.json()).data;
  const planned = await request.post('/api/v1/copilot/chat', {
    data: { message: '时滞补偿', dataset_id: dataset.dataset_id, active_version_id: dataset.version_id },
  });
  expect(planned.ok()).toBeTruthy();
  const execution = (await planned.json()).data;
  expect(execution.workflow_status).toBe('WAITING_CONFIRMATION');
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto(`/workspace/${execution.execution_id}`);
  await expect(page.locator('.approval-card').or(page.getByRole('button', { name: '进入工作台', exact: true }).first())).toBeVisible();
  // Enter through the actual landing gate on a fresh browser session.
  if (new URL(page.url()).pathname === '/') {
    await page.getByRole('button', { name: /进入工作台/ }).first().click();
  }
  await expect(page.locator('.approval-card')).toBeVisible();
  const confirmation = page.waitForResponse(r => r.url().endsWith('/copilot/confirm') && r.request().method() === 'POST');
  await page.getByRole('button', { name: '批准并继续' }).click();
  const response = await confirmation;
  expect(response.status(), await response.text()).toBe(200);
  const confirmed = (await response.json()).data;
  expect(confirmed.workflow_status).toBe('SUCCEEDED');
  expect(confirmed.result_version_id).toBeTruthy();
  expect(confirmed.result_version_id).not.toBe(dataset.version_id);
  await expect(page.locator('[data-test="execution-completed"]')).toBeVisible();
  await expect(page.locator('.plan-count')).toHaveText(`${execution.plan.steps.length}/${execution.plan.steps.length}`);
  await expect(page.locator('[data-test="lag-result-version"]')).toHaveText(confirmed.result_version_id);
  await expect(page.locator('.approval-card')).toHaveCount(0);
  const href = await page.getByRole('link', { name: '下载补偿后 CSV' }).getAttribute('href');
  const csv = await request.get(href!);
  expect(csv.status()).toBe(200);
  expect(csv.headers()['content-type']).toContain('text/csv');
  expect((await csv.text()).trim().split('\n').length - 1).toBe(confirmed.result_payload.summary.rows_after);
  await page.reload();
  await expect(page.locator('[data-test="lag-result-version"]')).toHaveText(confirmed.result_version_id);
  await expect(page.locator('.plan-count')).toHaveText(`${execution.plan.steps.length}/${execution.plan.steps.length}`);
  expect(errors).toEqual([]);
});
