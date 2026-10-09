import { expect, test } from '@playwright/test'

// Against the Prism mock: the data are the contract's examples (docs/api/openapi.json).

test('the shell loads with navigation and the API health', async ({ page }) => {
  await page.goto('/')
  await expect(page).toHaveURL(/\/topology$/)
  const nav = page.getByRole('navigation', { name: 'Ana menü' })
  for (const name of ['Harita', 'Cihazlar', 'Keşif']) {
    await expect(nav.getByRole('link', { name })).toBeVisible()
  }
  await expect(page.getByRole('status')).toContainText('API çalışıyor')
})

test('the devices list renders the inventory', async ({ page }) => {
  await page.goto('/devices')
  await expect(page.getByRole('heading', { name: 'Cihazlar' })).toBeVisible()
  const rows = page.getByRole('row')
  await expect(rows.filter({ hasText: 'core-sw-1' })).toBeVisible()
  await expect(rows.filter({ hasText: 'sw-b2-03' })).toContainText('Yönetiliyor')
  await page.getByRole('row').filter({ hasText: 'sw-b2-03' }).getByRole('link').click()
  await expect(page.getByRole('heading', { name: 'sw-b2-03' })).toBeVisible()
})

test('the map renders the topology nodes', async ({ page }) => {
  await page.goto('/topology')
  await expect(page.getByTestId('topology-summary')).toHaveText('5 düğüm, 3 bağlantı')
  const map = page.getByTestId('topology-map')
  await expect(map).toBeVisible()
  await expect(map.locator('canvas').first()).toBeVisible()
  // Every node is reachable without the mouse: through the search box.
  await page.getByRole('combobox', { name: 'Cihaz bul' }).click()
  await expect(page.getByRole('option')).toHaveCount(5)
})

test('the language can be switched to English', async ({ page }) => {
  await page.goto('/devices')
  await page.getByText('EN', { exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Devices' })).toBeVisible()
})
