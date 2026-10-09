import { expect, type Page, test } from '@playwright/test'

/**
 * Screenshots for documentation and pull requests, from the real stack with the fake lab
 * (after a discovery). Run: E2E_FAKELAB=1 npx playwright test --project=screenshots
 * Files go to docs/screenshots/ (SCREENSHOT_DIR to change).
 */
const OUT = process.env.SCREENSHOT_DIR ?? '../docs/screenshots'

async function settle(page: Page) {
  await page.waitForLoadState('networkidle')
  await page.waitForTimeout(800) // map animation and fonts
}

for (const scheme of ['light', 'dark'] as const) {
  test.describe(`${scheme} theme`, () => {
    test.use({ colorScheme: scheme })

    test(`pages (${scheme})`, async ({ page }) => {
      await page.goto('/topology')
      await expect(page.getByTestId('topology-summary')).toContainText('düğüm')
      await settle(page)
      await page.screenshot({ path: `${OUT}/map-l2-${scheme}.png` })

      await page.getByText('L3 (alt ağlar)').click()
      await settle(page)
      await page.screenshot({ path: `${OUT}/map-l3-${scheme}.png` })

      await page.goto('/devices')
      await expect(page.getByRole('row').filter({ hasText: 'core1' })).toBeVisible()
      await settle(page)
      await page.screenshot({ path: `${OUT}/devices-${scheme}.png`, fullPage: true })

      await page.getByRole('link', { name: 'dist2', exact: true }).click()
      await expect(page.getByRole('heading', { name: 'dist2' })).toBeVisible()
      await settle(page)
      await page.screenshot({ path: `${OUT}/device-detail-${scheme}.png`, fullPage: true })

      await page.goto('/discovery')
      await page.getByRole('link', { name: 'Ayrıntılar' }).first().click()
      await expect(page.getByText('Bulundu').first()).toBeVisible()
      await settle(page)
      await page.screenshot({ path: `${OUT}/discovery-run-${scheme}.png`, fullPage: true })
    })
  })
}
