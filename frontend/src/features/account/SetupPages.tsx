import { Button, Center, Group, Paper, Stack, Text, Title } from '@mantine/core'
import { IconLogout } from '@tabler/icons-react'
import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router'

import { useAuth, useMe } from '../../auth/context'
import { MfaEnrollment } from './MfaEnrollment'
import { PasswordForm } from './PasswordForm'

function SetupFrame({
  title,
  body,
  children,
}: {
  title: string
  body: string
  children: ReactNode
}) {
  const { t } = useTranslation()
  const { logout } = useAuth()
  const me = useMe()
  return (
    <Center mih="100vh" p="md">
      <Paper withBorder shadow="sm" p="xl" w={560} radius="md">
        <Stack gap="md">
          <Group justify="space-between">
            <Title order={1} size="h3">
              {title}
            </Title>
            <Button
              variant="subtle"
              size="xs"
              leftSection={<IconLogout size={14} />}
              onClick={() => void logout()}
            >
              {t('auth.logout')}
            </Button>
          </Group>
          <Text size="sm">{body}</Text>
          <Text size="xs" c="dimmed">
            {t('auth.signedInAs', { name: me.display_name, username: me.username })}
          </Text>
          {children}
        </Stack>
      </Paper>
    </Center>
  )
}

/** A session that must change its password first (new account, admin reset). */
export function SetupPasswordPage() {
  const { t } = useTranslation()
  const { reload } = useAuth()
  const navigate = useNavigate()
  return (
    <SetupFrame title={t('account.setup.passwordTitle')} body={t('account.setup.passwordBody')}>
      <PasswordForm
        onDone={() => {
          void reload().then(() => navigate('/', { replace: true }))
        }}
      />
    </SetupFrame>
  )
}

/** A session whose role requires MFA, before it is set up. */
export function SetupMfaPage() {
  const { t } = useTranslation()
  const { reload } = useAuth()
  const navigate = useNavigate()
  return (
    <SetupFrame title={t('account.setup.mfaTitle')} body={t('account.setup.mfaBody')}>
      <MfaEnrollment
        onDone={() => {
          void reload().then(() => navigate('/', { replace: true }))
        }}
      />
    </SetupFrame>
  )
}
