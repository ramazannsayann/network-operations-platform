import {
  Badge,
  Button,
  Card,
  Checkbox,
  Group,
  Modal,
  PasswordInput,
  SegmentedControl,
  Select,
  Skeleton,
  Stack,
  Table,
  Text,
  TextInput,
  Title,
} from '@mantine/core'
import { IconKey, IconPlus } from '@tabler/icons-react'
import { type FormEvent, useState } from 'react'
import { useTranslation } from 'react-i18next'

import type { Schemas } from '../../api/client'
import {
  useCreateCredentialProfile,
  useCredentialProfile,
  useCredentialProfiles,
  useDeleteCredentialProfile,
  useUpdateCredentialProfile,
} from '../../api/queries'
import { ProblemAlert } from '../../components/ProblemAlert'

type Kind = Schemas['CredentialKind']
const AUTH: Schemas['SnmpAuthProtocol'][] = ['sha', 'sha224', 'sha256', 'sha384', 'sha512']
const PRIV: Schemas['SnmpPrivProtocol'][] = ['aes128', 'aes192', 'aes256']

interface Form {
  name: string
  kind: Kind
  username: string
  password: string
  enable_secret: string
  clear_enable_secret: boolean
  auth_protocol: Schemas['SnmpAuthProtocol'] | null
  auth_key: string
  priv_protocol: Schemas['SnmpPrivProtocol'] | null
  priv_key: string
}

const EMPTY: Form = {
  name: '',
  kind: 'ssh',
  username: '',
  password: '',
  enable_secret: '',
  clear_enable_secret: false,
  auth_protocol: 'sha256',
  auth_key: '',
  priv_protocol: 'aes128',
  priv_key: '',
}

/** Only the fields that were typed: an empty secret field means "keep the stored one". */
function secrets(form: Form) {
  return {
    ...(form.password ? { password: form.password } : {}),
    ...(form.enable_secret ? { enable_secret: form.enable_secret } : {}),
    ...(form.auth_key ? { auth_key: form.auth_key } : {}),
    ...(form.priv_key ? { priv_key: form.priv_key } : {}),
  }
}

function ProfileForm({ id, onClose }: { id: string | null; onClose: () => void }) {
  const { t } = useTranslation()
  const detail = useCredentialProfile(id)
  const create = useCreateCredentialProfile()
  const update = useUpdateCredentialProfile()
  const remove = useDeleteCredentialProfile()
  const [form, setForm] = useState<Form>(EMPTY)
  const [loadedId, setLoadedId] = useState<string | null>(null)
  if (id !== null && detail.data && loadedId !== id) {
    setLoadedId(id)
    setForm({
      ...EMPTY,
      name: detail.data.name,
      kind: detail.data.kind,
      username: detail.data.username,
      auth_protocol: detail.data.auth_protocol,
      priv_protocol: detail.data.priv_protocol,
    })
  }
  const editing = id !== null
  const mutation = editing ? update : create
  const stored = t('admin.credentials.stored')
  const keep = t('admin.credentials.keep')
  const set = <K extends keyof Form>(key: K, value: Form[K]) => {
    setForm({ ...form, [key]: value })
  }

  const submit = (event: FormEvent) => {
    event.preventDefault()
    const snmp =
      form.kind === 'snmpv3'
        ? { auth_protocol: form.auth_protocol, priv_protocol: form.priv_protocol }
        : {}
    if (editing) {
      update.mutate(
        {
          id,
          body: {
            name: form.name,
            username: form.username,
            ...snmp,
            ...secrets(form),
            clear_enable_secret: form.clear_enable_secret,
          },
        },
        { onSuccess: onClose },
      )
    } else {
      create.mutate(
        { name: form.name, kind: form.kind, username: form.username, ...snmp, ...secrets(form) },
        { onSuccess: onClose },
      )
    }
  }

  if (editing && detail.isPending) return <Skeleton height={240} />
  return (
    <form onSubmit={submit} noValidate>
      <Stack gap="sm">
        {!editing && (
          <SegmentedControl
            value={form.kind}
            onChange={(value) => {
              set('kind', value)
            }}
            data={[
              { value: 'ssh', label: 'SSH' },
              { value: 'snmpv3', label: 'SNMPv3 (authPriv)' },
            ]}
          />
        )}
        <TextInput
          label={t('admin.credentials.name')}
          value={form.name}
          onChange={(event) => {
            set('name', event.currentTarget.value)
          }}
          required
        />
        <TextInput
          label={t('admin.credentials.username')}
          value={form.username}
          autoComplete="off"
          onChange={(event) => {
            set('username', event.currentTarget.value)
          }}
          required
        />
        {form.kind === 'ssh' ? (
          <>
            <PasswordInput
              label={t('admin.credentials.password')}
              placeholder={editing ? keep : undefined}
              description={editing ? stored : t('admin.credentials.writeOnly')}
              autoComplete="new-password"
              value={form.password}
              onChange={(event) => {
                set('password', event.currentTarget.value)
              }}
              required={!editing}
            />
            <PasswordInput
              label={t('admin.credentials.enableSecret')}
              placeholder={editing && detail.data?.enable_secret_set ? keep : undefined}
              description={
                editing && detail.data?.enable_secret_set ? stored : t('admin.credentials.optional')
              }
              autoComplete="new-password"
              value={form.enable_secret}
              disabled={form.clear_enable_secret}
              onChange={(event) => {
                set('enable_secret', event.currentTarget.value)
              }}
            />
            {editing && detail.data?.enable_secret_set && (
              <Checkbox
                label={t('admin.credentials.clearEnable')}
                checked={form.clear_enable_secret}
                onChange={(event) => {
                  set('clear_enable_secret', event.currentTarget.checked)
                }}
              />
            )}
          </>
        ) : (
          <>
            <Group grow>
              <Select
                label={t('admin.credentials.authProtocol')}
                data={AUTH}
                value={form.auth_protocol}
                onChange={(value) => {
                  set('auth_protocol', value)
                }}
                allowDeselect={false}
              />
              <Select
                label={t('admin.credentials.privProtocol')}
                data={PRIV}
                value={form.priv_protocol}
                onChange={(value) => {
                  set('priv_protocol', value)
                }}
                allowDeselect={false}
              />
            </Group>
            <PasswordInput
              label={t('admin.credentials.authKey')}
              placeholder={editing ? keep : undefined}
              description={editing ? stored : t('admin.credentials.writeOnly')}
              autoComplete="new-password"
              value={form.auth_key}
              onChange={(event) => {
                set('auth_key', event.currentTarget.value)
              }}
              required={!editing}
            />
            <PasswordInput
              label={t('admin.credentials.privKey')}
              placeholder={editing ? keep : undefined}
              description={editing ? stored : t('admin.credentials.writeOnly')}
              autoComplete="new-password"
              value={form.priv_key}
              onChange={(event) => {
                set('priv_key', event.currentTarget.value)
              }}
              required={!editing}
            />
          </>
        )}
        {editing && detail.data && (
          <Text size="xs" c="dimmed">
            {t('admin.credentials.usedBy', { count: detail.data.devices })}
          </Text>
        )}
        {mutation.isError && <ProblemAlert error={mutation.error} />}
        {remove.isError && <ProblemAlert error={remove.error} />}
        <Group justify="space-between">
          {editing ? (
            <Button
              color="red"
              variant="light"
              loading={remove.isPending}
              disabled={(detail.data?.devices ?? 0) > 0}
              onClick={() => {
                remove.mutate(id, { onSuccess: onClose })
              }}
            >
              {t('admin.credentials.delete')}
            </Button>
          ) : (
            <span />
          )}
          <Group>
            <Button variant="default" onClick={onClose}>
              {t('common.close')}
            </Button>
            <Button type="submit" loading={mutation.isPending}>
              {editing ? t('admin.credentials.save') : t('admin.credentials.create')}
            </Button>
          </Group>
        </Group>
      </Stack>
    </form>
  )
}

/** Kimlik profilleri: device credential profiles; secrets can be set, never seen again. */
export function CredentialsPage() {
  const { t } = useTranslation()
  const profiles = useCredentialProfiles()
  const [editing, setEditing] = useState<string | null>(null)
  return (
    <Stack gap="md">
      <Group justify="space-between">
        <Stack gap={0}>
          <Title order={2}>{t('admin.credentials.title')}</Title>
          <Text c="dimmed" size="sm">
            {t('admin.credentials.subtitle')}
          </Text>
        </Stack>
        <Button
          leftSection={<IconPlus size={16} />}
          onClick={() => {
            setEditing('new')
          }}
        >
          {t('admin.credentials.new')}
        </Button>
      </Group>
      {profiles.isError && <ProblemAlert error={profiles.error} />}
      {profiles.isPending && <Skeleton height={200} />}
      {profiles.data && (
        <Card withBorder padding={0}>
          <Table verticalSpacing="xs" highlightOnHover data-testid="credential-profiles">
            <Table.Thead>
              <Table.Tr>
                <Table.Th>{t('admin.credentials.name')}</Table.Th>
                <Table.Th>{t('admin.credentials.kind')}</Table.Th>
                <Table.Th />
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {profiles.data.items.map((profile) => (
                <Table.Tr key={profile.id}>
                  <Table.Td className="mono">{profile.name}</Table.Td>
                  <Table.Td>
                    <Badge variant="light" leftSection={<IconKey size={12} />}>
                      {profile.kind === 'ssh' ? 'SSH' : 'SNMPv3'}
                    </Badge>
                  </Table.Td>
                  <Table.Td>
                    <Button
                      size="xs"
                      variant="light"
                      onClick={() => {
                        setEditing(profile.id)
                      }}
                    >
                      {t('admin.credentials.edit')}
                    </Button>
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Card>
      )}
      <Modal
        opened={editing !== null}
        onClose={() => {
          setEditing(null)
        }}
        title={editing === 'new' ? t('admin.credentials.new') : t('admin.credentials.edit')}
      >
        {editing !== null && (
          <ProfileForm
            key={editing}
            id={editing === 'new' ? null : editing}
            onClose={() => {
              setEditing(null)
            }}
          />
        )}
      </Modal>
    </Stack>
  )
}
