import {
  Anchor,
  Button,
  Card,
  Group,
  Pagination,
  ScrollArea,
  Select,
  Skeleton,
  Stack,
  Table,
  Text,
  TextInput,
  Title,
  UnstyledButton,
} from '@mantine/core'
import { useDebouncedValue } from '@mantine/hooks'
import {
  IconChevronDown,
  IconChevronUp,
  IconRadar,
  IconSearch,
  IconSelector,
  IconServerOff,
} from '@tabler/icons-react'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useSearchParams } from 'react-router'

import type { Schemas } from '../../api/client'
import { type DeviceListQuery, useDevices, useLocations } from '../../api/queries'
import { EmptyState } from '../../components/EmptyState'
import { ProblemAlert } from '../../components/ProblemAlert'
import { RelativeTime } from '../../components/RelativeTime'
import { ManagementStatusBadge } from '../../components/StatusBadges'

const PAGE_SIZE = 25
const DEVICE_TYPES: Schemas['DeviceType'][] = [
  'router',
  'l3_switch',
  'switch',
  'firewall',
  'ap',
  'wlc',
  'unknown',
]
const ROLES: Schemas['DeviceRole'][] = ['edge', 'core', 'distribution', 'access', 'unknown']
const STATUSES: Schemas['ManagementStatus'][] = [
  'managed',
  'out_of_scope',
  'auth_failed',
  'unreachable',
  'unsupported_platform',
  'manual',
]
type Sort = NonNullable<DeviceListQuery['sort']>
type SortColumn = 'hostname' | 'mgmt_ip' | 'last_seen_at'

function SortHeader({
  column,
  label,
  sort,
  onSort,
}: {
  column: SortColumn
  label: string
  sort: Sort
  onSort: (sort: Sort) => void
}) {
  const { t } = useTranslation()
  const active = sort.replace('-', '') === column
  const descending = sort.startsWith('-')
  const IconComponent = !active ? IconSelector : descending ? IconChevronDown : IconChevronUp
  return (
    <Table.Th aria-sort={active ? (descending ? 'descending' : 'ascending') : 'none'}>
      <UnstyledButton
        onClick={() => {
          onSort(active && !descending ? (`-${column}` as Sort) : column)
        }}
        aria-label={t('devices.sortBy', { column: label })}
      >
        <Group gap={4} wrap="nowrap">
          <Text fw={600} size="sm">
            {label}
          </Text>
          <IconComponent size={14} aria-hidden />
        </Group>
      </UnstyledButton>
    </Table.Th>
  )
}

export function DevicesPage() {
  const { t } = useTranslation()
  const [params, setParams] = useSearchParams()
  const [search, setSearch] = useState(params.get('q') ?? '')
  const [debounced] = useDebouncedValue(search, 300)
  const page = Number(params.get('page') ?? '1') || 1
  const sort = (params.get('sort') ?? 'hostname') as Sort
  const type = params.get('type')
  const role = params.get('role')
  const status = params.get('status')
  const location = params.get('location')

  const update = (changes: Record<string, string | null>) => {
    const next = new URLSearchParams(params)
    for (const [key, value] of Object.entries(changes)) {
      if (value) next.set(key, value)
      else next.delete(key)
    }
    if (!('page' in changes)) next.delete('page')
    setParams(next, { replace: true })
  }

  useEffect(() => {
    if (debounced !== (params.get('q') ?? '')) update({ q: debounced || null })
    // eslint-disable-next-line react-hooks/exhaustive-deps -- only the debounced text matters
  }, [debounced])

  const query: DeviceListQuery = {
    sort,
    limit: PAGE_SIZE,
    offset: (page - 1) * PAGE_SIZE,
    ...(params.get('q') ? { q: params.get('q') ?? '' } : {}),
    ...(type ? { device_type: [type as Schemas['DeviceType']] } : {}),
    ...(role ? { role: [role as Schemas['DeviceRole']] } : {}),
    ...(status ? { management_status: [status as Schemas['ManagementStatus']] } : {}),
    ...(location ? { location_id: location } : {}),
  }
  const devices = useDevices(query)
  const locations = useLocations()
  const filtered = Boolean(params.get('q') || type || role || status || location)
  const total = devices.data?.total ?? 0

  return (
    <Stack gap="md">
      <Group justify="space-between">
        <Title order={2}>{t('devices.title')}</Title>
        {devices.data && <Text c="dimmed">{t('devices.count', { count: total })}</Text>}
      </Group>

      <Card withBorder padding="sm">
        <Group gap="sm" align="flex-end">
          <TextInput
            label={t('devices.search')}
            placeholder={t('devices.searchPlaceholder')}
            leftSection={<IconSearch size={16} aria-hidden />}
            value={search}
            onChange={(event) => {
              setSearch(event.currentTarget.value)
            }}
            w={260}
          />
          <Select
            label={t('devices.filterType')}
            placeholder={t('common.all')}
            clearable
            value={type}
            onChange={(value) => {
              update({ type: value })
            }}
            data={DEVICE_TYPES.map((value) => ({
              value,
              label: t(`enums.deviceType.${value}`),
            }))}
            w={160}
          />
          <Select
            label={t('devices.filterRole')}
            placeholder={t('common.all')}
            clearable
            value={role}
            onChange={(value) => {
              update({ role: value })
            }}
            data={ROLES.map((value) => ({ value, label: t(`enums.role.${value}`) }))}
            w={160}
          />
          <Select
            label={t('devices.filterStatus')}
            placeholder={t('common.all')}
            clearable
            value={status}
            onChange={(value) => {
              update({ status: value })
            }}
            data={STATUSES.map((value) => ({
              value,
              label: t(`enums.managementStatus.${value}`),
            }))}
            w={220}
          />
          <Select
            label={t('devices.filterLocation')}
            placeholder={t('common.all')}
            clearable
            searchable
            value={location}
            onChange={(value) => {
              update({ location: value })
            }}
            data={(locations.data?.items ?? []).map((item) => ({
              value: item.id,
              label: item.path,
            }))}
            w={220}
          />
        </Group>
      </Card>

      {devices.isError && (
        <ProblemAlert error={devices.error} onRetry={() => void devices.refetch()} />
      )}

      {devices.isPending && <Skeleton height={240} />}

      {devices.data && total === 0 && !filtered && (
        <EmptyState
          icon={IconServerOff}
          title={t('devices.empty.title')}
          body={t('devices.empty.body')}
          action={
            <Button component={Link} to="/discovery" leftSection={<IconRadar size={16} />}>
              {t('devices.empty.action')}
            </Button>
          }
        />
      )}
      {devices.data && total === 0 && filtered && <Text c="dimmed">{t('devices.noMatch')}</Text>}

      {devices.data && total > 0 && (
        <Card withBorder padding={0}>
          <ScrollArea>
            <Table striped highlightOnHover verticalSpacing="xs" miw={900}>
              <Table.Thead>
                <Table.Tr>
                  <SortHeader
                    column="hostname"
                    label={t('devices.columns.hostname')}
                    sort={sort}
                    onSort={(value) => {
                      update({ sort: value })
                    }}
                  />
                  <SortHeader
                    column="mgmt_ip"
                    label={t('devices.columns.mgmtIp')}
                    sort={sort}
                    onSort={(value) => {
                      update({ sort: value })
                    }}
                  />
                  <Table.Th>{t('devices.columns.type')}</Table.Th>
                  <Table.Th>{t('devices.columns.role')}</Table.Th>
                  <Table.Th>{t('devices.columns.status')}</Table.Th>
                  <Table.Th>{t('devices.columns.model')}</Table.Th>
                  <Table.Th>{t('devices.columns.serials')}</Table.Th>
                  <SortHeader
                    column="last_seen_at"
                    label={t('devices.columns.lastSeen')}
                    sort={sort}
                    onSort={(value) => {
                      update({ sort: value })
                    }}
                  />
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {devices.data.items.map((device) => (
                  <Table.Tr key={device.id}>
                    <Table.Td>
                      <Anchor component={Link} to={`/devices/${device.id}`} fw={600}>
                        {device.hostname ?? device.mgmt_ip ?? device.id}
                      </Anchor>
                    </Table.Td>
                    <Table.Td className="mono">{device.mgmt_ip ?? t('common.none')}</Table.Td>
                    <Table.Td>{t(`enums.deviceType.${device.device_type}`)}</Table.Td>
                    <Table.Td>{t(`enums.role.${device.role}`)}</Table.Td>
                    <Table.Td>
                      <ManagementStatusBadge status={device.management_status} />
                    </Table.Td>
                    <Table.Td>{device.model ?? t('common.none')}</Table.Td>
                    <Table.Td className="mono">
                      {device.serials.length > 0 ? device.serials.join(', ') : t('common.none')}
                    </Table.Td>
                    <Table.Td>
                      <RelativeTime value={device.last_seen_at} />
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </ScrollArea>
        </Card>
      )}

      {total > PAGE_SIZE && (
        <Pagination
          total={Math.ceil(total / PAGE_SIZE)}
          value={page}
          onChange={(value) => {
            update({ page: String(value) })
          }}
          aria-label={t('common.page')}
        />
      )}
    </Stack>
  )
}
