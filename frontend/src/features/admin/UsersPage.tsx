import {
  Badge,
  Button,
  Card,
  Group,
  Menu,
  Modal,
  Pagination,
  PasswordInput,
  ScrollArea,
  Select,
  Skeleton,
  Stack,
  Table,
  Text,
  TextInput,
  Title,
  ActionIcon,
} from '@mantine/core'
import { useDebouncedValue } from '@mantine/hooks'
import {
  IconDots,
  IconLock,
  IconLockOpen,
  IconPlus,
  IconSearch,
  IconShieldCheck,
  IconShieldOff,
  IconUserOff,
} from '@tabler/icons-react'
import { type FormEvent, useState } from 'react'
import { useTranslation } from 'react-i18next'

import type { Schemas } from '../../api/client'
import {
  useCreateUser,
  useResetPassword,
  useUpdateUser,
  useUserAction,
  useUsers,
} from '../../api/queries'
import { useMe } from '../../auth/context'
import { ProblemAlert } from '../../components/ProblemAlert'
import { RelativeTime } from '../../components/RelativeTime'
import { fieldErrors, passwordMessageKey } from '../account/problems'

type User = Schemas['User']
type Role = Schemas['UserRole']
const ROLES: Role[] = ['admin', 'operator', 'viewer']
const PAGE_SIZE = 25

function CreateUser({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation()
  const create = useCreateUser()
  const [form, setForm] = useState({
    username: '',
    display_name: '',
    email: '',
    role: 'viewer' as Role,
    password: '',
  })
  const errors = fieldErrors(create.error)
  const submit = (event: FormEvent) => {
    event.preventDefault()
    create.mutate(
      { ...form, email: form.email || null },
      {
        onSuccess: onClose,
      },
    )
  }
  const set = (key: keyof typeof form) => (value: string) => {
    setForm({ ...form, [key]: value })
  }
  return (
    <form onSubmit={submit} noValidate>
      <Stack gap="sm">
        <TextInput
          label={t('admin.users.username')}
          value={form.username}
          onChange={(event) => {
            set('username')(event.currentTarget.value)
          }}
          error={errors.username ? t('admin.users.usernameRule') : undefined}
          required
        />
        <TextInput
          label={t('admin.users.name')}
          value={form.display_name}
          onChange={(event) => {
            set('display_name')(event.currentTarget.value)
          }}
          required
        />
        <TextInput
          label={t('admin.users.email')}
          type="email"
          value={form.email}
          onChange={(event) => {
            set('email')(event.currentTarget.value)
          }}
        />
        <Select
          label={t('admin.users.role')}
          data={ROLES.map((role) => ({ value: role, label: t(`enums.userRole.${role}`) }))}
          value={form.role}
          onChange={(value) => {
            if (value) set('role')(value)
          }}
          allowDeselect={false}
        />
        <PasswordInput
          label={t('admin.users.temporaryPassword')}
          description={t('admin.users.temporaryHelp')}
          autoComplete="new-password"
          value={form.password}
          onChange={(event) => {
            set('password')(event.currentTarget.value)
          }}
          error={
            (errors.password ?? [])
              .map((type) => t(passwordMessageKey(type), { min: 12 }))
              .join(' ') || undefined
          }
          required
        />
        {create.isError && !errors.password && !errors.username && (
          <ProblemAlert error={create.error} />
        )}
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>
            {t('common.close')}
          </Button>
          <Button type="submit" loading={create.isPending}>
            {t('admin.users.create')}
          </Button>
        </Group>
      </Stack>
    </form>
  )
}

function ResetPassword({ user, onClose }: { user: User; onClose: () => void }) {
  const { t } = useTranslation()
  const reset = useResetPassword()
  const [password, setPassword] = useState('')
  const errors = fieldErrors(reset.error)
  return (
    <Stack gap="sm">
      <Text size="sm">{t('admin.users.resetPasswordBody', { username: user.username })}</Text>
      <PasswordInput
        label={t('admin.users.temporaryPassword')}
        description={t('admin.users.resetOptional')}
        autoComplete="new-password"
        value={password}
        onChange={(event) => {
          setPassword(event.currentTarget.value)
        }}
        error={
          (errors.temporary_password ?? [])
            .map((type) => t(passwordMessageKey(type), { min: 12 }))
            .join(' ') || undefined
        }
      />
      {reset.isError && !errors.temporary_password && <ProblemAlert error={reset.error} />}
      <Group justify="flex-end">
        <Button variant="default" onClick={onClose}>
          {t('common.close')}
        </Button>
        <Button
          color="orange"
          loading={reset.isPending}
          onClick={() => {
            reset.mutate(
              { id: user.id, body: password ? { temporary_password: password } : {} },
              { onSuccess: onClose },
            )
          }}
        >
          {t('admin.users.resetPassword')}
        </Button>
      </Group>
    </Stack>
  )
}

function locked(user: User): boolean {
  return user.locked_until !== null && new Date(user.locked_until).getTime() > Date.now()
}

/** Kullanıcılar: users, their roles and state; create, change role, deactivate, resets. */
export function UsersPage() {
  const { t } = useTranslation()
  const me = useMe()
  const [search, setSearch] = useState('')
  const [q] = useDebouncedValue(search, 300)
  const [page, setPage] = useState(1)
  const [creating, setCreating] = useState(false)
  const [resetting, setResetting] = useState<User | null>(null)
  const users = useUsers({ limit: PAGE_SIZE, offset: (page - 1) * PAGE_SIZE, ...(q ? { q } : {}) })
  const update = useUpdateUser()
  const action = useUserAction()
  const error = update.error ?? action.error

  return (
    <Stack gap="md">
      <Group justify="space-between">
        <Title order={2}>{t('admin.users.title')}</Title>
        <Button
          leftSection={<IconPlus size={16} />}
          onClick={() => {
            setCreating(true)
          }}
        >
          {t('admin.users.new')}
        </Button>
      </Group>
      <Card withBorder padding="sm">
        <TextInput
          aria-label={t('admin.users.search')}
          placeholder={t('admin.users.search')}
          leftSection={<IconSearch size={16} />}
          value={search}
          onChange={(event) => {
            setSearch(event.currentTarget.value)
            setPage(1)
          }}
          maw={360}
        />
      </Card>
      {error && <ProblemAlert error={error} />}
      {users.isError && <ProblemAlert error={users.error} />}
      {users.isPending && <Skeleton height={240} />}
      {users.data && (
        <Card withBorder padding={0}>
          <ScrollArea>
            <Table verticalSpacing="xs" miw={980} data-testid="users-table">
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>{t('admin.users.username')}</Table.Th>
                  <Table.Th>{t('admin.users.name')}</Table.Th>
                  <Table.Th>{t('admin.users.role')}</Table.Th>
                  <Table.Th>{t('admin.users.state')}</Table.Th>
                  <Table.Th>MFA</Table.Th>
                  <Table.Th>{t('admin.users.lastLogin')}</Table.Th>
                  <Table.Th />
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {users.data.items.map((user) => (
                  <Table.Tr key={user.id}>
                    <Table.Td className="mono">{user.username}</Table.Td>
                    <Table.Td>
                      <Text size="sm">{user.display_name}</Text>
                      {user.email && (
                        <Text size="xs" c="dimmed">
                          {user.email}
                        </Text>
                      )}
                    </Table.Td>
                    <Table.Td>
                      <Select
                        size="xs"
                        w={140}
                        aria-label={t('admin.users.roleOf', { username: user.username })}
                        data={ROLES.map((role) => ({
                          value: role,
                          label: t(`enums.userRole.${role}`),
                        }))}
                        value={user.role}
                        allowDeselect={false}
                        disabled={user.id === me.id}
                        onChange={(value) => {
                          if (value && value !== user.role)
                            update.mutate({ id: user.id, body: { role: value } })
                        }}
                      />
                    </Table.Td>
                    <Table.Td>
                      <Group gap={4}>
                        {user.is_active ? (
                          <Badge color="teal" variant="light">
                            {t('admin.users.active')}
                          </Badge>
                        ) : (
                          <Badge
                            color="gray"
                            variant="light"
                            leftSection={<IconUserOff size={12} />}
                          >
                            {t('admin.users.inactive')}
                          </Badge>
                        )}
                        {locked(user) && (
                          <Badge
                            color="orange"
                            variant="light"
                            leftSection={<IconLock size={12} />}
                          >
                            {t('admin.users.locked')}
                          </Badge>
                        )}
                        {user.must_change_password && (
                          <Badge color="gray" variant="outline">
                            {t('admin.users.mustChange')}
                          </Badge>
                        )}
                      </Group>
                    </Table.Td>
                    <Table.Td>
                      {user.mfa_enabled ? (
                        <Badge
                          color="teal"
                          variant="light"
                          leftSection={<IconShieldCheck size={12} />}
                        >
                          {t('account.mfa.on')}
                        </Badge>
                      ) : (
                        <Badge
                          color="gray"
                          variant="light"
                          leftSection={<IconShieldOff size={12} />}
                        >
                          {t('account.mfa.off')}
                        </Badge>
                      )}
                    </Table.Td>
                    <Table.Td>
                      <RelativeTime value={user.last_login_at} />
                    </Table.Td>
                    <Table.Td>
                      <Menu position="bottom-end">
                        <Menu.Target>
                          <ActionIcon
                            variant="subtle"
                            aria-label={t('admin.users.actionsFor', { username: user.username })}
                          >
                            <IconDots size={16} />
                          </ActionIcon>
                        </Menu.Target>
                        <Menu.Dropdown>
                          {user.is_active ? (
                            <Menu.Item
                              color="red"
                              disabled={user.id === me.id}
                              onClick={() => {
                                action.mutate({ id: user.id, action: 'deactivate' })
                              }}
                            >
                              {t('admin.users.deactivate')}
                            </Menu.Item>
                          ) : (
                            <Menu.Item
                              onClick={() => {
                                update.mutate({ id: user.id, body: { is_active: true } })
                              }}
                            >
                              {t('admin.users.activate')}
                            </Menu.Item>
                          )}
                          <Menu.Item
                            disabled={!user.mfa_enabled}
                            onClick={() => {
                              action.mutate({ id: user.id, action: 'reset-mfa' })
                            }}
                          >
                            {t('admin.users.resetMfa')}
                          </Menu.Item>
                          <Menu.Item
                            onClick={() => {
                              setResetting(user)
                            }}
                          >
                            {t('admin.users.resetPassword')}
                          </Menu.Item>
                          <Menu.Item
                            leftSection={<IconLockOpen size={14} />}
                            disabled={!locked(user)}
                            onClick={() => {
                              action.mutate({ id: user.id, action: 'unlock' })
                            }}
                          >
                            {t('admin.users.unlock')}
                          </Menu.Item>
                        </Menu.Dropdown>
                      </Menu>
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </ScrollArea>
        </Card>
      )}
      {(users.data?.total ?? 0) > PAGE_SIZE && (
        <Pagination
          total={Math.ceil((users.data?.total ?? 0) / PAGE_SIZE)}
          value={page}
          onChange={setPage}
          aria-label={t('common.page')}
        />
      )}
      <Modal
        opened={creating}
        onClose={() => {
          setCreating(false)
        }}
        title={t('admin.users.new')}
      >
        <CreateUser
          onClose={() => {
            setCreating(false)
          }}
        />
      </Modal>
      <Modal
        opened={resetting !== null}
        onClose={() => {
          setResetting(null)
        }}
        title={t('admin.users.resetPassword')}
      >
        {resetting && (
          <ResetPassword
            user={resetting}
            onClose={() => {
              setResetting(null)
            }}
          />
        )}
      </Modal>
    </Stack>
  )
}
