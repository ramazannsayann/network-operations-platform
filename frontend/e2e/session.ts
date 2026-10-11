import { execFileSync } from 'node:child_process'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

import { expect, type Page } from '@playwright/test'

import { currentStep, totp } from './totp.ts'

export const ROOT = fileURLToPath(new URL('../..', import.meta.url))

export function make(...args: string[]) {
  execFileSync('make', args, { cwd: ROOT, stdio: 'inherit' })
}

/** FAKELAB_UI_PASSWORD from deploy/.env (make fakelab-users writes it there). */
export function uiPassword(): string {
  const line = readFileSync(`${ROOT}/deploy/.env`, 'utf8')
    .split('\n')
    .find((entry) => entry.startsWith('FAKELAB_UI_PASSWORD='))
  if (!line) throw new Error('run make fakelab-users first')
  return line.slice('FAKELAB_UI_PASSWORD='.length)
}

// A TOTP code is accepted once: remember the last step used and wait for the next one.
let lastStep = 0

export async function freshCode(secret: string, page: Page): Promise<string> {
  while (currentStep() <= lastStep) await page.waitForTimeout(1000)
  lastStep = currentStep()
  return totp(secret, lastStep)
}

export async function signIn(page: Page, username: string, secret?: string) {
  await page.goto('/login')
  await page.getByLabel('Kullanıcı adı').fill(username)
  await page.getByLabel('Parola').fill(uiPassword())
  await page.getByRole('button', { name: 'Oturum aç' }).click()
  if (secret) {
    await expect(page.getByRole('heading', { name: 'İki adımlı doğrulama' })).toBeVisible()
    await typeCode(page, await freshCode(secret, page))
    await page.getByRole('button', { name: 'Doğrula' }).click()
  }
  await expect(page.getByRole('navigation', { name: 'Ana menü' })).toBeVisible()
}

export async function signOut(page: Page) {
  await page.getByRole('button', { name: 'Hesap' }).click()
  await page.getByRole('menuitem', { name: 'Çıkış yap' }).click()
  await expect(page.getByRole('heading', { name: 'Oturum aç' })).toBeVisible()
}

/** The admin's TOTP secret, set up in the first test of a run. */
export const admin = { username: 'fakelab-admin', secret: '' }

/** The page's current access token (for API calls the test makes on its own). */
export async function bearer(page: Page): Promise<string> {
  const response = await page.request.post('/api/v1/auth/refresh')
  expect(response.ok()).toBeTruthy()
  const body = (await response.json()) as { access_token: string }
  return body.access_token
}

/** Type a 6-digit code into the PinInput (focus moves from box to box by itself). */
export async function typeCode(page: Page, code: string) {
  await page.getByRole('textbox', { name: 'Doğrulama kodu 1/6' }).click()
  await page.keyboard.type(code)
}

/** Reset the fake lab admin's MFA, sign in and enroll again; returns the new secret. */
export async function enrollAdmin(page: Page, before?: () => Promise<void>): Promise<string> {
  make('fakelab-users')
  make('fakelab-mfa-reset', 'USERNAME=fakelab-admin')
  await page.goto('/login')
  await page.getByLabel('Kullanıcı adı').fill(admin.username)
  await page.getByLabel('Parola').fill(uiPassword())
  await page.getByRole('button', { name: 'Oturum aç' }).click()
  await expect(page).toHaveURL(/\/setup\/mfa$/)
  if (before) await before()
  await page.getByRole('button', { name: 'Kuruluma başla' }).click()
  const secret = (await page.getByTestId('mfa-secret').innerText()).replace(/\s/g, '')
  await typeCode(page, await freshCode(secret, page))
  await page.getByRole('button', { name: 'Doğrula ve aç' }).click()
  await page.getByLabel('Kurtarma kodlarını güvenli bir yere kaydettim').check()
  await page.getByRole('button', { name: 'Bitir' }).click()
  await expect(page.getByRole('navigation', { name: 'Ana menü' })).toBeVisible()
  admin.secret = secret
  return secret
}
