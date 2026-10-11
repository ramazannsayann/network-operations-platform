import {
  Badge,
  Button,
  Card,
  Group,
  Modal,
  PasswordInput,
  ScrollArea,
  SimpleGrid,
  Stack,
  Table,
  Text,
  TextInput,
  Title,
} from '@mantine/core'
import { IconShieldCheck, IconShieldOff } from '@tabler/icons-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { useDisableMfa, useRevokeSession, useSessions } from '../../api/queries'
import { useAuth, useMe } from '../../auth/context'
import { ProblemAlert } from '../../components/ProblemAlert'
import { RelativeTime } from '../../components/RelativeTime'
import { MfaEnrollment } from './MfaEnrollment'
import { PasswordForm } from './PasswordForm'

function DisableMfa({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation()
  const { reload } = useAuth()
  const disable = useDisableMfa()
  const [password, setPassword] = useState('')
  const [code, setCode] = useState('')
  return (
    <Stack gap="sm">
      <Text size="sm">{t('account.mfa.disableBody')}</Text>
      <PasswordInput
        label={t('account.password.current')}
        autoComplete="current-password"
        value={password}
        onChange={(event) => {
          setPassword(event.currentTarget.value)
        }}
      />
      <TextInput
        label={t('account.mfa.codeOrRecovery')}
        autoComplete="one-time-code"
        value={code}
        onChange={(event) => {
          setCode(event.currentTarget.value)
        }}
      />
      {disable.isError && <ProblemAlert error={disable.error} />}
      <Group justify="flex-end">
        <Button variant="default" onClick={onClose}>
          {t('common.close')}
        </Button>
        <Button
          color="red"
          loading={disable.isPending}
          disabled={!password || !code}
          onClick={() => {
            const factor = /^\d{6}$/.test(code.trim())
              ? { code: code.trim() }
              : { recovery_code: code.trim() }
            disable.mutate(
              { password, ...factor },
              {
                onSuccess: () => {
                  onClose()
                  void reload()
                },
              },
            )
          }}
        >
          {t('account.mfa.disable')}
        </Button>
      </Group>
    </Stack>
  )
}

function Sessions() {
  const { t } = useTranslation()
  const sessions = useSessions()
  const revoke = useRevokeSession()
  const { logout } = useAuth()
  return (
    <Card withBorder>
      <Title order={3} size="h4" mb="sm">
        {t('account.sessions.title')}
      </Title>
      {sessions.isError && <ProblemAlert error={sessions.error} />}
      {sessions.data && (
        <ScrollArea>
          <Table verticalSpacing="xs" miw={640} data-testid="sessions">
            <Table.Thead>
              <Table.Tr>
                <Table.Th>{t('account.sessions.started')}</Table.Th>
                <Table.Th>{t('account.sessions.lastUsed')}</Table.Th>
                <Table.Th>{t('account.sessions.address')}</Table.Th>
                <Table.Th>{t('account.sessions.browser')}</Table.Th>
                <Table.Th />
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {sessions.data.items.map((session) => (
                <Table.Tr key={session.id}>
                  <Table.Td>
                    <RelativeTime value={session.started_at} />
                  </Table.Td>
                  <Table.Td>
                    <RelativeTime value={session.last_used_at} />
                  </Table.Td>
                  <Table.Td className="mono">{session.ip ?? t('common.none')}</Table.Td>
                  <Table.Td maw={320}>
                    <Text size="xs" lineClamp={2}>
                      {session.user_agent ?? t('common.unknown')}
                    </Text>
                  </Table.Td>
                  <Table.Td>
                    {session.current ? (
                      <Badge variant="light">{t('account.sessions.current')}</Badge>
                    ) : (
                      <Button
                        size="xs"
                        variant="light"
                        color="red"
                        loading={revoke.isPending && revoke.variables === session.id}
                        onClick={() => {
                          revoke.mutate(session.id)
                        }}
                      >
                        {t('account.sessions.end')}
                      </Button>
                    )}
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </ScrollArea>
      )}
      <Group mt="sm">
        <Button variant="default" size="xs" onClick={() => void logout()}>
          {t('account.sessions.endThis')}
        </Button>
      </Group>
    </Card>
  )
}

/** The signed-in user's own account: password, two-factor authentication, sessions. */
export function ProfilePage() {
  const { t } = useTranslation()
  const me = useMe()
  const { reload } = useAuth()
  const [enrolling, setEnrolling] = useState(false)
  const [disabling, setDisabling] = useState(false)
  return (
    <Stack gap="md">
      <Title order={2}>{t('account.title')}</Title>
      <Card withBorder>
        <SimpleGrid cols={{ base: 1, sm: 2, md: 4 }}>
          <div>
            <Text size="xs" c="dimmed">
              {t('account.username')}
            </Text>
            <Text fw={500} className="mono">
              {me.username}
            </Text>
          </div>
          <div>
            <Text size="xs" c="dimmed">
              {t('account.name')}
            </Text>
            <Text fw={500}>{me.display_name}</Text>
          </div>
          <div>
            <Text size="xs" c="dimmed">
              {t('account.role')}
            </Text>
            <Badge variant="light">{t(`enums.userRole.${me.role}`)}</Badge>
          </div>
          <div>
            <Text size="xs" c="dimmed">
              {t('account.lastLogin')}
            </Text>
            <RelativeTime value={me.last_login_at} />
          </div>
        </SimpleGrid>
      </Card>
      <SimpleGrid cols={{ base: 1, lg: 2 }}>
        <Card withBorder>
          <Title order={3} size="h4" mb="sm">
            {t('account.password.title')}
          </Title>
          <PasswordForm />
        </Card>
        <Card withBorder>
          <Group justify="space-between" mb="sm">
            <Title order={3} size="h4">
              {t('account.mfa.title')}
            </Title>
            {me.mfa_enabled ? (
              <Badge color="teal" variant="light" leftSection={<IconShieldCheck size={12} />}>
                {t('account.mfa.on')}
              </Badge>
            ) : (
              <Badge color="gray" variant="light" leftSection={<IconShieldOff size={12} />}>
                {t('account.mfa.off')}
              </Badge>
            )}
          </Group>
          <Text size="sm" mb="sm">
            {me.mfa_required ? t('account.mfa.requiredForRole') : t('account.mfa.optional')}
          </Text>
          {me.mfa_enabled ? (
            <Button
              variant="light"
              color="red"
              onClick={() => {
                setDisabling(true)
              }}
            >
              {t('account.mfa.disable')}
            </Button>
          ) : enrolling ? (
            <MfaEnrollment
              onDone={() => {
                setEnrolling(false)
                void reload()
              }}
            />
          ) : (
            <Button
              onClick={() => {
                setEnrolling(true)
              }}
            >
              {t('account.mfa.enable')}
            </Button>
          )}
        </Card>
      </SimpleGrid>
      <Sessions />
      <Modal
        opened={disabling}
        onClose={() => {
          setDisabling(false)
        }}
        title={t('account.mfa.disable')}
      >
        <DisableMfa
          onClose={() => {
            setDisabling(false)
          }}
        />
      </Modal>
    </Stack>
  )
}
