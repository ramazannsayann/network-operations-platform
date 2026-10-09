import { expect, test } from '@playwright/test'

/**
 * The real stack with the fake lab, driven through the UI (not run in CI):
 *
 *   make fakelab-up fakelab-seed
 *   cd frontend && npm run e2e:fakelab
 *
 * Discovers the fake lab from core1 and checks the map: lab/fakelab/topology.yaml has 11
 * devices and 14 cables, of which two form one EtherChannel, so 13 logical links.
 */
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
