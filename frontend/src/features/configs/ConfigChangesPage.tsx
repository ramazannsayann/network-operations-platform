import {
  Card,
  Group,
  Pagination,
  SegmentedControl,
  Select,
  Skeleton,
  Stack,
  Text,
  TextInput,
  Title,
} from '@mantine/core'
import { useDebouncedValue } from '@mantine/hooks'
import { IconHistoryOff } from '@tabler/icons-react'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useSearchParams } from 'react-router'

import type { Schemas } from '../../api/client'
import { type ConfigChangesQuery, useConfigChanges } from '../../api/queries'
import { EmptyState } from '../../components/EmptyState'
import { ProblemAlert } from '../../components/ProblemAlert'
import { ChangesTable } from './ChangesTable'
import { DeviceSelect } from './DeviceSelect'
import { parseRange, RANGES, rangeStart } from './timeRange'

const PAGE_SIZE = 25

/** Every detected configuration change, filterable by device, origin, user and time. */
export function ConfigChangesPage() {
  const { t } = useTranslation()
  const [params, setParams] = useSearchParams()
  const [user, setUser] = useState(params.get('user') ?? '')
  const [debouncedUser] = useDebouncedValue(user, 400)
  const page = Number(params.get('page') ?? '1') || 1
  const device = params.get('device')
  const origin = params.get('origin')
  const range = parseRange(params.get('range'), '30d')

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
    if (debouncedUser !== (params.get('user') ?? '')) update({ user: debouncedUser || null })
    // eslint-disable-next-line react-hooks/exhaustive-deps -- only the debounced text matters
  }, [debouncedUser])

  const from = rangeStart(range)
  const query: ConfigChangesQuery = {
    limit: PAGE_SIZE,
    offset: (page - 1) * PAGE_SIZE,
    ...(device ? { device_id: device } : {}),
    ...(origin ? { origin: [origin as Schemas['ChangeOrigin']] } : {}),
    ...(params.get('user') ? { username: params.get('user') ?? '' } : {}),
    ...(from ? { from } : {}),
  }
  const changes = useConfigChanges(query)
  const total = changes.data?.total ?? 0

  return (
    <Stack gap="md">
      <Group justify="space-between">
        <Title order={2}>{t('configs.changes.pageTitle')}</Title>
        {changes.data && <Text c="dimmed">{t('configs.changes.count', { count: total })}</Text>}
      </Group>
      <Card withBorder padding="sm">
        <Group gap="sm" align="flex-end">
          <DeviceSelect
            value={device}
            onChange={(value) => {
              update({ device: value })
            }}
          />
          <Stack gap={4}>
            <Text size="sm" fw={500}>
              {t('configs.changes.origin')}
            </Text>
            <SegmentedControl
              value={origin ?? 'all'}
              onChange={(value) => {
                update({ origin: value === 'all' ? null : value })
              }}
              data={[
                { value: 'all', label: t('common.all') },
                { value: 'external', label: t('configs.origin.externalShort') },
                { value: 'platform', label: t('configs.origin.platform') },
              ]}
            />
          </Stack>
          <TextInput
            label={t('configs.changes.user')}
            placeholder={t('configs.changes.userPlaceholder')}
            value={user}
            onChange={(event) => {
              setUser(event.currentTarget.value)
            }}
            w={180}
          />
          <Select
            label={t('filters.range')}
            data={RANGES.map((value) => ({ value, label: t(`filters.ranges.${value}`) }))}
            value={range}
            onChange={(value) => {
              update({ range: value })
            }}
            allowDeselect={false}
            w={160}
          />
        </Group>
      </Card>
      {changes.isError && (
        <ProblemAlert error={changes.error} onRetry={() => void changes.refetch()} />
      )}
      {changes.isPending && <Skeleton height={240} />}
      {changes.data && total === 0 && (
        <EmptyState icon={IconHistoryOff} title={t('configs.changes.none')} />
      )}
      {changes.data && total > 0 && (
        <Card withBorder padding={0}>
          <ChangesTable items={changes.data.items} showDevice />
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
