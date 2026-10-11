import { expect, type Page, test } from '@playwright/test'

import { enrollAdmin, signOut } from './session.ts'

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
      test.setTimeout(240_000)
      // The admin's MFA is reset and set up again (no secret is kept between runs); the
      // enrollment page is captured before it shows a secret.
      await enrollAdmin(page, async () => {
        await settle(page)
        await page.screenshot({ path: `${OUT}/setup-mfa-${scheme}.png` })
      })
      await page.goto('/topology')
      await expect(page.getByTestId('topology-summary')).toContainText('düğüm')
      await settle(page)
      await page.screenshot({ path: `${OUT}/map-l2-${scheme}.png` })

      await page.getByText('L3 (alt ağlar)').click()
      await settle(page)
      await page.screenshot({ path: `${OUT}/map-l3-${scheme}.png` })

      await page.getByText('L2 (fiziksel)').click()
      await page.getByRole('button', { name: /Zaman/ }).click()
      await page.getByRole('button', { name: '1 saat önce' }).click()
      await expect(page.getByTestId('historic-banner')).toBeVisible()
      await page.keyboard.press('Escape')
      await settle(page)
      await page.screenshot({ path: `${OUT}/map-history-${scheme}.png` })

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

      // M4: needs backups and at least one change of dist1 (make fakelab-backup,
      // make fakelab-change DEVICE=dist1 SCENARIO=remove-vlan-from-trunk).
      await page.goto('/configs')
      await expect(page.getByRole('row').filter({ hasText: 'dist1' })).toBeVisible()
      await settle(page)
      await page.screenshot({ path: `${OUT}/configs-${scheme}.png`, fullPage: true })

      await page.getByRole('link', { name: 'dist1', exact: true }).click()
      await expect(page.getByTestId('config-timeline')).toBeVisible()
      await expect(page.getByRole('table', { name: 'Konfigürasyon' })).toBeVisible()
      await settle(page)
      await page.screenshot({ path: `${OUT}/config-tab-${scheme}.png`, fullPage: true })

      await page.locator('label', { hasText: 'Karşılaştır' }).click()
      await expect(page.getByTestId('config-diff')).toBeVisible()
      await settle(page)
      await page.screenshot({ path: `${OUT}/config-diff-split-${scheme}.png`, fullPage: true })
      await page.locator('label', { hasText: 'Birleşik' }).click()
      await expect(page.getByRole('table', { name: 'Birleşik' })).toBeVisible()
      await settle(page)
      await page.screenshot({ path: `${OUT}/config-diff-unified-${scheme}.png`, fullPage: true })

      await page.goto('/config-changes')
      await expect(page.getByTestId('config-changes')).toBeVisible()
      await settle(page)
      await page.screenshot({ path: `${OUT}/config-changes-${scheme}.png`, fullPage: true })

      await page.goto('/events')
      await expect(page.getByTestId('events-table')).toBeVisible()
      await settle(page)
      await page.screenshot({ path: `${OUT}/events-${scheme}.png`, fullPage: true })

      // M7: administration and the own account.
      await page.goto('/admin/users')
      await expect(page.getByTestId('users-table')).toContainText('fakelab-viewer')
      await settle(page)
      await page.screenshot({ path: `${OUT}/admin-users-${scheme}.png`, fullPage: true })

      await page.goto('/admin/credentials')
      await page.getByRole('row').filter({ hasText: 'fakelab' }).last().getByRole('button').click()
      await expect(page.getByRole('dialog')).toContainText('Kayıtlı değer gösterilmez')
      await settle(page)
      await page.screenshot({ path: `${OUT}/admin-credentials-${scheme}.png` })
      await page.keyboard.press('Escape')

      await page.goto('/admin/audit')
      await expect(page.getByTestId('audit-table')).toContainText('auth.login')
      await settle(page)
      await page.screenshot({ path: `${OUT}/admin-audit-${scheme}.png`, fullPage: true })

      await page.goto('/profile')
      await expect(page.getByTestId('sessions')).toBeVisible()
      await settle(page)
      await page.screenshot({ path: `${OUT}/profile-${scheme}.png`, fullPage: true })

      await signOut(page)
      await settle(page)
      await page.screenshot({ path: `${OUT}/login-${scheme}.png` })
    })
  })
}
