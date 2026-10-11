import { expect, test } from '@playwright/test'

// Against the Prism mock: the data are the contract's examples (docs/api/openapi.json).

test('the shell loads with navigation and the API health', async ({ page }) => {
  await page.goto('/')
  await expect(page).toHaveURL(/\/topology$/)
  const nav = page.getByRole('navigation', { name: 'Ana menü' })
  for (const name of [
    'Harita',
    'Cihazlar',
    'Keşif',
    'Config',
    'Config değişiklikleri',
    'Olaylar',
  ]) {
    await expect(nav.getByRole('link', { name, exact: true })).toBeVisible()
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

test('time travel: presets, the historical banner and back to now', async ({ page }) => {
  await page.goto('/topology')
  await expect(page.getByTestId('topology-summary')).toHaveText('5 düğüm, 3 bağlantı')
  await page.getByRole('button', { name: /Zaman/ }).click()
  await page.getByRole('button', { name: '1 saat önce' }).click()
  const banner = page.getByTestId('historic-banner')
  await expect(banner).toContainText('Geçmiş görünüm:')
  // Turkish date format, 24 h.
  await expect(banner).toContainText(/\d{2}\.\d{2}\.\d{4} \d{2}:\d{2}/)
  await banner.getByRole('button', { name: 'Şimdiye dön' }).click()
  await expect(banner).toBeHidden()
})

test('config backups, a device Config tab with viewer and diff, and its changes', async ({
  page,
}) => {
  await page.goto('/configs')
  await expect(page.getByRole('heading', { name: 'Konfigürasyon yedekleri' })).toBeVisible()
  const row = page.getByRole('row').filter({ hasText: 'dist-sw-b' })
  await expect(row).toContainText('2 değişiklik')
  await row.getByRole('link', { name: 'dist-sw-b' }).click()
  await expect(page).toHaveURL(/tab=config/)

  await expect(page.getByTestId('config-timeline')).toBeVisible()
  const viewer = page.getByRole('table', { name: 'Konfigürasyon' })
  await expect(viewer).toContainText('hostname dist-sw-b')
  // Secrets arrive redacted and show as a marker, never as the raw value.
  await expect(viewer.getByRole('img', { name: 'gizli' })).toBeVisible()

  await page.locator('label', { hasText: 'Karşılaştır' }).click()
  const split = page.getByRole('table', { name: 'Yan yana' })
  await expect(split).toContainText('switchport trunk allowed vlan 30,99')
  await page.locator('label', { hasText: 'Birleşik' }).click()
  await expect(page.getByRole('table', { name: 'Birleşik' })).toContainText(
    'switchport trunk allowed vlan 20,30,99',
  )

  const changes = page.getByTestId('config-changes')
  await expect(changes.getByText('Platform dışı değişiklik').first()).toBeVisible()
  await expect(changes).toContainText('jdoe')
  await expect(changes).toContainText('zamanlanmış yedekte bulundu')
})

test('the global change list and the events view', async ({ page }) => {
  await page.goto('/config-changes')
  await expect(page.getByRole('heading', { name: 'Config değişiklikleri' })).toBeVisible()
  await expect(page.getByTestId('config-changes')).toContainText(
    'switchport trunk allowed vlan remove 20',
  )
  await page.getByRole('link', { name: 'Olaylar' }).click()
  await expect(page.getByRole('heading', { name: 'Olaylar' })).toBeVisible()
  const events = page.getByTestId('events-table')
  await expect(events).toContainText('SYS-5-CONFIG_I')
  await expect(events).toContainText('Configured from console by jdoe on vty0')
})
