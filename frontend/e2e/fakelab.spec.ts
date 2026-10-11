import { expect, test } from '@playwright/test'

import { admin, bearer, freshCode, make, signIn, signOut, typeCode, uiPassword } from './session.ts'

/**
 * The real stack with the fake lab, driven through the UI (not run in CI):
 *
 *   make fakelab-up fakelab-seed fakelab-users
 *   cd frontend && npm run e2e:fakelab
 *
 * Signs in as the fake lab's admin, who must set up MFA first (its MFA is reset at the
 * start, so the run always goes through enrollment; the TOTP codes are computed from the
 * secret the page shows). Discovers the fake lab from core1 and checks the map:
 * lab/fakelab/topology.yaml has 11 devices and 14 cables, of which two form one
 * EtherChannel, so 13 logical links. Then changes a fake device outside the platform
 * (make fakelab-change, which also sends the device's syslog) and waits for the change to
 * show up in the change list. A viewer sees no administration.
 */
const DEVICES = 11
const LOGICAL_LINKS = 13

test.describe.configure({ mode: 'serial' })

test.beforeAll(() => {
  make('fakelab-users')
  make('fakelab-mfa-reset', 'USERNAME=fakelab-admin')
})

test('the admin must set up MFA, then signs in with a TOTP code', async ({ page }) => {
  await page.goto('/devices')
  await expect(page).toHaveURL(/\/login\?next=%2Fdevices/)
  await page.getByLabel('Kullanıcı adı').fill(admin.username)
  await page.getByLabel('Parola').fill('not the password at all')
  await page.getByRole('button', { name: 'Oturum aç' }).click()
  await expect(page.getByRole('alert')).toContainText('Kullanıcı adı veya parola hatalı')
  await page.getByLabel('Parola').fill(uiPassword())
  await page.getByRole('button', { name: 'Oturum aç' }).click()

  // Forced enrollment: nothing else opens before it.
  await expect(page).toHaveURL(/\/setup\/mfa$/)
  await page.getByRole('button', { name: 'Kuruluma başla' }).click()
  await expect(
    page.getByRole('img', { name: 'Kimlik doğrulama uygulaması için QR kodu' }),
  ).toBeVisible()
  admin.secret = (await page.getByTestId('mfa-secret').innerText()).replace(/\s/g, '')
  expect(admin.secret).toMatch(/^[A-Z2-7]{32}$/)
  await typeCode(page, await freshCode(admin.secret, page))
  await page.getByRole('button', { name: 'Doğrula ve aç' }).click()
  const codes = page.getByTestId('recovery-codes')
  await expect(codes.locator('p')).toHaveCount(10)
  await page.getByLabel('Kurtarma kodlarını güvenli bir yere kaydettim').check()
  await page.getByRole('button', { name: 'Bitir' }).click()
  await expect(page.getByRole('navigation', { name: 'Ana menü' })).toBeVisible()
  await expect(page.getByRole('link', { name: 'Kullanıcılar' })).toBeVisible()

  await signOut(page)
  // After signing out the old session is gone: protected pages send back to the login.
  await page.goto('/devices')
  await expect(page).toHaveURL(/\/login/)
  await signIn(page, admin.username, admin.secret)
  await page.getByRole('link', { name: 'Denetim kaydı' }).click()
  const audit = page.getByTestId('audit-table')
  await expect(audit).toContainText('auth.mfa.enroll')
  await expect(audit).toContainText('auth.login')
})

test('discover the fake lab from the UI and see it on the map', async ({ page }) => {
  await signIn(page, admin.username, admin.secret)
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
  await signIn(page, admin.username, admin.secret)
  // A fresh backup first (what the nightly job does), finished before the change: a
  // backup running during the change window would record it without its user.
  const requested = Date.now()
  make('fakelab-backup')
  const token = await bearer(page)
  await expect
    .poll(
      async () => {
        const response = await request.get('/api/v1/config-backups?q=dist1', {
          headers: { Authorization: `Bearer ${token}` },
        })
        const body = (await response.json()) as { items: { last_backup_at: string | null }[] }
        const last = body.items[0]?.last_backup_at
        return last ? new Date(last).getTime() : 0
      },
      { timeout: 60_000 },
    )
    .toBeGreaterThan(requested)

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

test('a viewer sees no administration and cannot start a discovery', async ({ page }) => {
  await signIn(page, 'fakelab-viewer')
  const nav = page.getByRole('navigation', { name: 'Ana menü' })
  await expect(nav.getByRole('link', { name: 'Cihazlar' })).toBeVisible()
  for (const name of ['Kullanıcılar', 'Kimlik profilleri', 'Denetim kaydı']) {
    await expect(nav.getByRole('link', { name })).toHaveCount(0)
  }
  await page.goto('/admin/users')
  await expect(page.getByRole('heading', { name: 'Bu sayfaya erişiminiz yok' })).toBeVisible()
  await page.goto('/discovery')
  await expect(page.getByText('Rolünüz keşif başlatamaz')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Keşfi başlat' })).toHaveCount(0)
  await signOut(page)
})
