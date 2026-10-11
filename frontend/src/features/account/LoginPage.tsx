import {
  Alert,
  Anchor,
  Button,
  Center,
  Group,
  Paper,
  PasswordInput,
  PinInput,
  SegmentedControl,
  Stack,
  Text,
  TextInput,
  Title,
} from '@mantine/core'
import { IconAlertTriangle, IconTopologyStar3 } from '@tabler/icons-react'
import { type FormEvent, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Navigate, useNavigate, useSearchParams } from 'react-router'

import { ApiError } from '../../api/errors'
import { useAuth } from '../../auth/context'
import { LANGUAGES } from '../../i18n'

function safeNext(value: string | null): string {
  // Only paths of this app: never redirect to another site after signing in.
  return value?.startsWith('/') && !value.startsWith('//') ? value : '/'
}

function useErrorText() {
  const { t } = useTranslation()
  return (error: unknown, stage: 'password' | 'code'): string => {
    if (error instanceof ApiError && error.status === 429) return t('auth.login.rateLimited')
    if (error instanceof ApiError && error.status === 401) {
      return stage === 'code' ? t('auth.login.wrongCode') : t('auth.login.failed')
    }
    return t('common.error')
  }
}

/** Sign in: username and password, then a TOTP or recovery code where MFA is on. */
export function LoginPage() {
  const { t, i18n } = useTranslation()
  const { state, login, verifyMfa } = useAuth()
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const next = safeNext(params.get('next'))
  const errorText = useErrorText()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [challenge, setChallenge] = useState<string | null>(null)
  const [useRecovery, setUseRecovery] = useState(false)
  const [code, setCode] = useState('')
  const [recoveryCode, setRecoveryCode] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  if (state.status === 'authenticated') return <Navigate to={next} replace />

  const run = async (stage: 'password' | 'code', work: () => Promise<void>) => {
    setBusy(true)
    setError(null)
    try {
      await work()
    } catch (caught) {
      setError(errorText(caught, stage))
    } finally {
      setBusy(false)
    }
  }

  const submitPassword = (event: FormEvent) => {
    event.preventDefault()
    void run('password', async () => {
      const result = await login(username, password)
      setPassword('')
      if (result.status === 'mfa_required') setChallenge(result.challenge)
      else void navigate(next, { replace: true })
    })
  }

  const submitCode = (event: FormEvent) => {
    event.preventDefault()
    if (challenge === null) return
    void run('code', async () => {
      await verifyMfa(challenge, useRecovery ? { recovery_code: recoveryCode } : { code })
      void navigate(next, { replace: true })
    })
  }

  return (
    <Center mih="100vh" p="md">
      <Paper withBorder shadow="sm" p="xl" w={380} radius="md">
        <Stack gap="md">
          <Group justify="space-between">
            <Group gap="xs">
              <IconTopologyStar3 size={28} aria-hidden />
              <div>
                <Title order={1} size="h3">
                  {t('app.title')}
                </Title>
                <Text size="xs" c="dimmed">
                  {t('app.subtitle')}
                </Text>
              </div>
            </Group>
            <SegmentedControl
              size="xs"
              aria-label={t('header.language')}
              value={i18n.language}
              onChange={(language) => void i18n.changeLanguage(language)}
              data={LANGUAGES.map((language) => ({
                value: language,
                label: language.toUpperCase(),
              }))}
            />
          </Group>
          <Title order={2} size="h4">
            {challenge === null ? t('auth.login.title') : t('auth.login.mfaTitle')}
          </Title>
          {error && (
            <Alert color="red" variant="light" icon={<IconAlertTriangle size={16} />} role="alert">
              {error}
            </Alert>
          )}
          {challenge === null ? (
            <form onSubmit={submitPassword} noValidate>
              <Stack gap="sm">
                <TextInput
                  label={t('auth.login.username')}
                  autoComplete="username"
                  value={username}
                  onChange={(event) => {
                    setUsername(event.currentTarget.value)
                  }}
                  autoFocus
                  required
                />
                <PasswordInput
                  label={t('auth.login.password')}
                  autoComplete="current-password"
                  value={password}
                  onChange={(event) => {
                    setPassword(event.currentTarget.value)
                  }}
                  required
                />
                <Button type="submit" loading={busy} disabled={!username || !password}>
                  {t('auth.login.submit')}
                </Button>
              </Stack>
            </form>
          ) : (
            <form onSubmit={submitCode} noValidate>
              <Stack gap="sm">
                {useRecovery ? (
                  <TextInput
                    label={t('auth.login.recoveryCode')}
                    placeholder="xxxxx-xxxxx"
                    autoComplete="off"
                    value={recoveryCode}
                    onChange={(event) => {
                      setRecoveryCode(event.currentTarget.value)
                    }}
                    autoFocus
                  />
                ) : (
                  <Stack gap={4}>
                    <Text size="sm" fw={500}>
                      {t('auth.login.code')}
                    </Text>
                    <PinInput
                      length={6}
                      type="number"
                      oneTimeCode
                      autoFocus
                      value={code}
                      onChange={setCode}
                      ariaLabel={t('auth.login.code')}
                      getInputProps={(index) => ({
                        'aria-label': `${t('auth.login.code')} ${String(index + 1)}/6`,
                      })}
                    />
                    <Text size="xs" c="dimmed">
                      {t('auth.login.codeHelp')}
                    </Text>
                  </Stack>
                )}
                <Button
                  type="submit"
                  loading={busy}
                  disabled={useRecovery ? !recoveryCode : code.length !== 6}
                >
                  {t('auth.login.verify')}
                </Button>
                <Group justify="space-between">
                  <Anchor
                    component="button"
                    type="button"
                    size="sm"
                    onClick={() => {
                      setUseRecovery(!useRecovery)
                      setError(null)
                    }}
                  >
                    {useRecovery ? t('auth.login.useCode') : t('auth.login.useRecovery')}
                  </Anchor>
                  <Anchor
                    component="button"
                    type="button"
                    size="sm"
                    c="dimmed"
                    onClick={() => {
                      setChallenge(null)
                      setCode('')
                      setRecoveryCode('')
                      setError(null)
                    }}
                  >
                    {t('auth.login.back')}
                  </Anchor>
                </Group>
              </Stack>
            </form>
          )}
        </Stack>
      </Paper>
    </Center>
  )
}
