import { execFileSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'

import { expect, test } from '@playwright/test'

/**
 * The real stack with the fake lab, driven through the UI (not run in CI):
 *
 *   make fakelab-up fakelab-seed
 *   cd frontend && npm run e2e:fakelab
 *
 * Discovers the fake lab from core1 and checks the map: lab/fakelab/topology.yaml has 11
 * devices and 14 cables, of which two form one EtherChannel, so 13 logical links. Then
 * changes a fake device outside the platform (make fakelab-change, which also sends the
 * device's syslog) and waits for the change to show up in the change list.
 */
const ROOT = fileURLToPath(new URL('../..', import.meta.url))

function make(...args: string[]) {
  execFileSync('make', args, { cwd: ROOT, stdio: 'inherit' })
}
const DEVICES = 11
const LOGICAL_LINKS = 13

test('discover the fake lab from the UI and see it on the map', async ({ page }) => {
  await page.goto('/discovery')
  await page
    .getByLabel(/Başlangıç adresleri/)
    .first()
    .fill('10.255.0.2,')
  await page
    .getByLabel(/İzin verilen alt ağlar/)
    .first()
    .fill('10.255.0.0/24,')
  const profiles = page.getByRole('combobox', { name: /Kimlik bilgisi profilleri/ })
  for (const profile of ['fakelab-outdated', 'fakelab']) {
    await profiles.click()
    await page.getByRole('option', { name: profile, exact: true }).click()
  }
  await page.keyboard.press('Escape')
  await page.getByRole('button', { name: 'Keşfi başlat' }).click()

  await expect(page).toHaveURL(/\/discovery\/runs\//)
  await expect(page.getByText('Tamamlandı').first()).toBeVisible({ timeout: 150_000 })
  await expect(page.getByRole('button', { name: /Bulundu\s*8/ })).toBeVisible()
  await expect(page.getByRole('button', { name: /Aynı cihazın başka adresi\s*1/ })).toBeVisible()
  await expect(page.getByRole('button', { name: /Kapsam dışı\s*1/ })).toBeVisible()

  await page.getByRole('link', { name: 'Harita' }).click()
  await expect(page.getByTestId('topology-summary')).toHaveText(
    `${DEVICES} düğüm, ${LOGICAL_LINKS} bağlantı`,
  )
  await page.getByRole('combobox', { name: 'Cihaz bul' }).click()
  await expect(page.getByRole('option')).toHaveCount(DEVICES)
})

test('a change made outside the platform appears in the change list', async ({ page, request }) => {
  test.setTimeout(240_000)
  // A baseline version first (what the nightly backup does).
  make('fakelab-backup')
  await expect
    .poll(
      async () => {
        const response = await request.get('/api/v1/config-backups?q=dist1')
        const body = (await response.json()) as { items: { version_count: number }[] }
        return body.items[0]?.version_count ?? 0
      },
      { timeout: 60_000 },
    )
    .toBeGreaterThan(0)

  const text = `uplink to access2 (e2e ${String(Date.now())})`
  make('fakelab-change', 'DEVICE=dist1', 'SCENARIO=change-description', `TEXT=${text}`)

  await page.goto('/config-changes')
  const row = page.getByTestId('config-changes').getByRole('row').filter({ hasText: text })
  // The 30 s change window, the backup, then the list's next refresh.
  await expect(row).toBeVisible({ timeout: 120_000 })
  await expect(row).toContainText('Platform dışı değişiklik')
  await expect(row).toContainText('jdoe')
  await expect(row).toContainText('192.0.2.77')
  await row.getByRole('link', { name: 'Farkı göster' }).click()
  await expect(page.getByTestId('config-diff')).toContainText(`description ${text}`)
})
