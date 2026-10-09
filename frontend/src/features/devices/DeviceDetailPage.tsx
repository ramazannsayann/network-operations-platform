import {
  Alert,
  Anchor,
  Badge,
  Button,
  Card,
  Group,
  Loader,
  ScrollArea,
  SimpleGrid,
  Skeleton,
  Stack,
  Table,
  Text,
  TextInput,
  Title,
} from '@mantine/core'
import { useQueryClient } from '@tanstack/react-query'
import { IconArrowLeft, IconCheck, IconRefresh, IconSearch, IconX } from '@tabler/icons-react'
import { type ReactNode, useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useParams } from 'react-router'

import type { Schemas } from '../../api/client'
import { keys, useDevice, useInterfaces, useJob, useRefreshDevice } from '../../api/queries'
import { ProblemAlert } from '../../components/ProblemAlert'
import { RelativeTime } from '../../components/RelativeTime'
import { CollectionStatusBadge, ManagementStatusBadge } from '../../components/StatusBadges'
import { speed, vlanList } from '../../lib/format'

type Interface = Schemas['InterfaceSummary']

function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <Text size="xs" c="dimmed" component="dt">
        {label}
      </Text>
      <Text component="dd" m={0} fw={500}>
        {children}
      </Text>
    </div>
  )
}

function InterfaceStatus({ item }: { item: Interface }) {
  const { t } = useTranslation()
  const state = item.state
  if (!state) return <>{t('common.none')}</>
  if (state.err_disabled_reason)
    return (
      <Badge color="red" variant="light" leftSection={<IconX size={12} aria-hidden />}>
        {t('device.interfaces.errDisabled')}
      </Badge>
    )
  if (state.admin_up === false)
    return (
      <Badge color="gray" variant="light">
        {t('device.interfaces.adminDown')}
      </Badge>
    )
  return state.oper_up ? (
    <Badge color="teal" variant="light" leftSection={<IconCheck size={12} aria-hidden />}>
      {t('device.interfaces.up')}
    </Badge>
  ) : (
    <Badge color="orange" variant="light" leftSection={<IconX size={12} aria-hidden />}>
      {t('device.interfaces.down')}
    </Badge>
  )
}

function vlans(item: Interface, native: (vlan: number) => string): string {
  const state = item.state
  if (!state) return ''
  if (state.switchport_mode === 'access' && state.access_vlan) return String(state.access_vlan)
  if (state.switchport_mode === 'trunk') {
    const allowed = state.allowed_vlans ? vlanList(state.allowed_vlans) : 'all'
    return state.native_vlan ? `${allowed} (${native(state.native_vlan)})` : allowed
  }
  return ''
}

function RefreshButton({ device }: { device: Schemas['Device'] }) {
  const { t } = useTranslation()
  const client = useQueryClient()
  const refresh = useRefreshDevice(device.id)
  const [jobId, setJobId] = useState<string | null>(null)
  const job = useJob(jobId)
  const status = job.data?.status

  useEffect(() => {
    if (status === 'succeeded' || status === 'failed') {
      void client.invalidateQueries({ queryKey: keys.device(device.id) })
      void client.invalidateQueries({ queryKey: keys.interfaces(device.id) })
    }
  }, [status, client, device.id])

  const busy = refresh.isPending || status === 'queued' || status === 'running'
  return (
    <Stack gap="xs" align="flex-end">
      <Button
        leftSection={busy ? <Loader size={14} /> : <IconRefresh size={16} aria-hidden />}
        onClick={() => {
          refresh.mutate(undefined, {
            onSuccess: (ref) => {
              setJobId(ref.id)
            },
          })
        }}
        disabled={busy || !device.is_managed}
        title={device.is_managed ? undefined : t('device.refresh.notManaged')}
      >
        {busy ? t('device.refresh.running') : t('device.refresh.button')}
      </Button>
      <div aria-live="polite">
        {status === 'succeeded' && (
          <Text size="sm" c="teal">
            {t('device.refresh.done')}
          </Text>
        )}
        {status === 'failed' && (
          <Text size="sm" c="red">
            {t('device.refresh.failed', { error: job.data?.error?.detail ?? '' })}
          </Text>
        )}
      </div>
      {refresh.isError && <ProblemAlert error={refresh.error} />}
    </Stack>
  )
}

export function DeviceDetailPage() {
  const { t } = useTranslation()
  const { deviceId = '' } = useParams()
  const device = useDevice(deviceId)
  const interfaces = useInterfaces(deviceId)
  const [filter, setFilter] = useState('')

  const parents = useMemo(() => {
    const byId = new Map((interfaces.data?.items ?? []).map((item) => [item.id, item.name]))
    return byId
  }, [interfaces.data])
  const shown = (interfaces.data?.items ?? []).filter((item) => {
    const text = `${item.name} ${item.name_normalized} ${item.description ?? ''}`.toLowerCase()
    return text.includes(filter.toLowerCase())
  })

  if (device.isError) {
    return (
      <Stack>
        <Anchor component={Link} to="/devices">
          <Group gap={4}>
            <IconArrowLeft size={16} aria-hidden />
            {t('device.back')}
          </Group>
        </Anchor>
        <ProblemAlert error={device.error} onRetry={() => void device.refetch()} />
      </Stack>
    )
  }
  if (!device.data) return <Skeleton height={320} />
  const d = device.data

  return (
    <Stack gap="md">
      <Anchor component={Link} to="/devices" size="sm">
        <Group gap={4}>
          <IconArrowLeft size={16} aria-hidden />
          {t('device.back')}
        </Group>
      </Anchor>
      <Group justify="space-between" align="flex-start">
        <Stack gap={4}>
          <Title order={2}>{d.hostname ?? d.mgmt_ip ?? d.id}</Title>
          <Group gap="xs">
            <ManagementStatusBadge status={d.management_status} />
            <Badge variant="outline">{t(`enums.deviceType.${d.device_type}`)}</Badge>
            <Badge variant="outline">{t(`enums.role.${d.role}`)}</Badge>
          </Group>
        </Stack>
        <RefreshButton device={d} />
      </Group>

      {!d.is_managed && (
        <Alert color="gray" variant="light">
          {t('device.refresh.notManaged')}
        </Alert>
      )}

      <Card withBorder>
        <Title order={3} size="h4" mb="sm">
          {t('device.facts')}
        </Title>
        <SimpleGrid cols={{ base: 1, sm: 2, md: 4 }} component="dl" spacing="md" m={0}>
          <Fact label={t('device.model')}>{d.model ?? t('common.unknown')}</Fact>
          <Fact label={t('device.os')}>
            {d.os_family === 'unknown' ? t('common.unknown') : d.os_family.toUpperCase()}{' '}
            {d.os_version ?? ''}
          </Fact>
          <Fact label={t('device.mgmtIp')}>
            <span className="mono">{d.mgmt_ip ?? t('common.none')}</span>
          </Fact>
          <Fact label={t('device.location')}>{d.location?.path ?? t('common.none')}</Fact>
          <Fact label={t('device.serials')}>
            {d.serial_details.length === 0
              ? t('common.none')
              : d.serial_details.map((serial) => (
                  <span key={serial.serial} className="mono" style={{ display: 'block' }}>
                    {serial.serial}
                    {serial.stack_member !== null &&
                      ` (${t('device.stackMember', { member: serial.stack_member })})`}
                  </span>
                ))}
          </Fact>
          <Fact label={t('device.reachability')}>{t(`enums.reachability.${d.reachability}`)}</Fact>
          <Fact label={t('device.discoveredVia')}>
            {t(`enums.discoverySource.${d.discovered_via}`)}
          </Fact>
          <Fact label={t('device.lastPolled')}>
            <RelativeTime value={d.last_polled_at} />
          </Fact>
        </SimpleGrid>
      </Card>

      <Card withBorder>
        <Title order={3} size="h4" mb="sm">
          {t('device.freshness.title')}
        </Title>
        {d.collections.length === 0 ? (
          <Text c="dimmed">{t('device.freshness.empty')}</Text>
        ) : (
          <ScrollArea>
            <Table verticalSpacing={4} miw={560}>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>{t('device.freshness.kind')}</Table.Th>
                  <Table.Th>{t('device.freshness.lastStatus')}</Table.Th>
                  <Table.Th>{t('device.freshness.lastRun')}</Table.Th>
                  <Table.Th>{t('device.freshness.lastSuccess')}</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {d.collections.map((collection) => (
                  <Table.Tr key={collection.kind}>
                    <Table.Td>{t(`enums.collectionKind.${collection.kind}`)}</Table.Td>
                    <Table.Td>
                      <CollectionStatusBadge status={collection.last_status} />
                    </Table.Td>
                    <Table.Td>
                      <RelativeTime value={collection.last_started_at} />
                    </Table.Td>
                    <Table.Td>
                      <RelativeTime value={collection.last_success_at} />
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </ScrollArea>
        )}
      </Card>

      <Card withBorder>
        <Group justify="space-between" mb="sm">
          <Title order={3} size="h4">
            {t('device.interfaces.title')}
            {interfaces.data && (
              <Text span c="dimmed" size="sm" ml="xs">
                {t('device.interfaces.count', { count: interfaces.data.total })}
              </Text>
            )}
          </Title>
          <TextInput
            aria-label={t('device.interfaces.filter')}
            placeholder={t('device.interfaces.filter')}
            leftSection={<IconSearch size={16} aria-hidden />}
            value={filter}
            onChange={(event) => {
              setFilter(event.currentTarget.value)
            }}
            size="xs"
          />
        </Group>
        {interfaces.isError && <ProblemAlert error={interfaces.error} />}
        {interfaces.isPending && <Skeleton height={160} />}
        {interfaces.data?.total === 0 && <Text c="dimmed">{t('device.interfaces.empty')}</Text>}
        {shown.length > 0 && (
          <ScrollArea>
            <Table striped verticalSpacing={4} miw={1000}>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>{t('device.interfaces.name')}</Table.Th>
                  <Table.Th>{t('device.interfaces.status')}</Table.Th>
                  <Table.Th>{t('device.interfaces.speed')}</Table.Th>
                  <Table.Th>{t('device.interfaces.mode')}</Table.Th>
                  <Table.Th>{t('device.interfaces.vlans')}</Table.Th>
                  <Table.Th>{t('device.interfaces.channel')}</Table.Th>
                  <Table.Th>{t('device.interfaces.description')}</Table.Th>
                  <Table.Th>{t('device.interfaces.mac')}</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {shown.map((item) => (
                  <Table.Tr key={item.id}>
                    <Table.Td className="mono">{item.name}</Table.Td>
                    <Table.Td>
                      <InterfaceStatus item={item} />
                    </Table.Td>
                    <Table.Td>
                      {[speed(item.state?.speed_mbps), item.state?.duplex]
                        .filter(Boolean)
                        .join(' / ') || t('common.none')}
                    </Table.Td>
                    <Table.Td>{item.state?.switchport_mode ?? t('common.none')}</Table.Td>
                    <Table.Td className="mono">
                      {vlans(item, (vlan) => t('device.interfaces.native', { vlan })) ||
                        t('common.none')}
                    </Table.Td>
                    <Table.Td className="mono">
                      {item.parent_interface_id
                        ? (parents.get(item.parent_interface_id) ?? '?')
                        : t('common.none')}
                    </Table.Td>
                    <Table.Td>{item.description ?? ''}</Table.Td>
                    <Table.Td className="mono">{item.mac ?? ''}</Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </ScrollArea>
        )}
      </Card>
    </Stack>
  )
}
