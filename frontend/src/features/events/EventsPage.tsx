import {
  Anchor,
  Badge,
  Card,
  Group,
  MultiSelect,
  Pagination,
  ScrollArea,
  Select,
  Skeleton,
  Stack,
  Switch,
  Table,
  TagsInput,
  Text,
  Title,
} from '@mantine/core'
import { IconMessageOff } from '@tabler/icons-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useSearchParams } from 'react-router'

import { type EventsQuery, useEvents } from '../../api/queries'
import { EmptyState } from '../../components/EmptyState'
import { ProblemAlert } from '../../components/ProblemAlert'
import { RelativeTime } from '../../components/RelativeTime'
import { DeviceSelect } from '../configs/DeviceSelect'
import { parseRange, RANGES, rangeStart } from '../configs/timeRange'

const PAGE_SIZE = 50
const SEVERITIES = [0, 1, 2, 3, 4, 5, 6, 7] as const
// Syslog severity colours: only the levels that signal a problem get warning colours.
const SEVERITY_COLOR = ['red', 'red', 'red', 'orange', 'yellow', 'blue', 'gray', 'gray'] as const
const COMMON_MNEMONICS = [
  'SYS-5-CONFIG_I',
  'PARSER-5-CFGLOG_LOGGEDCMD',
  'LINK-3-UPDOWN',
  'LINK-5-CHANGED',
  'LINEPROTO-5-UPDOWN',
]

export function SeverityBadge({ severity }: { severity: number | null }) {
  const { t } = useTranslation()
  if (severity === null) return <>{t('common.none')}</>
  return (
    <Badge color={SEVERITY_COLOR[severity]} variant="light" style={{ overflow: 'visible' }}>
      {severity} · {t(`events.severity.${severity}`)}
    </Badge>
  )
}

/** Syslog messages from managed devices (the events service), with filters. */
export function EventsPage() {
  const { t } = useTranslation()
  const [params, setParams] = useSearchParams()
  const [live, setLive] = useState(true)
  const page = Number(params.get('page') ?? '1') || 1
  const device = params.get('device')
  const severity = params.getAll('severity').map(Number)
  const mnemonic = params.getAll('mnemonic')
  const range = parseRange(params.get('range'), '24h')

  const update = (key: string, values: string[]) => {
    const next = new URLSearchParams(params)
    next.delete(key)
    for (const value of values) next.append(key, value)
    next.delete('page')
    setParams(next, { replace: true })
  }

  const from = rangeStart(range)
  const query: EventsQuery = {
    limit: PAGE_SIZE,
    offset: (page - 1) * PAGE_SIZE,
    ...(device ? { device_id: device } : {}),
    ...(severity.length ? { severity } : {}),
    ...(mnemonic.length ? { mnemonic } : {}),
    ...(from ? { from } : {}),
  }
  const events = useEvents(query, live)
  const total = events.data?.total ?? 0

  return (
    <Stack gap="md">
      <Group justify="space-between">
        <Stack gap={0}>
          <Title order={2}>{t('events.title')}</Title>
          <Text c="dimmed" size="sm">
            {t('events.subtitle')}
          </Text>
        </Stack>
        <Group>
          {events.data && <Text c="dimmed">{t('events.count', { count: total })}</Text>}
          <Switch
            label={t('events.live')}
            checked={live}
            onChange={(event) => {
              setLive(event.currentTarget.checked)
            }}
          />
        </Group>
      </Group>
      <Card withBorder padding="sm">
        <Group gap="sm" align="flex-end">
          <DeviceSelect
            value={device}
            onChange={(value) => {
              update('device', value ? [value] : [])
            }}
          />
          <MultiSelect
            label={t('events.severityFilter')}
            placeholder={severity.length ? undefined : t('common.all')}
            data={SEVERITIES.map((level) => ({
              value: String(level),
              label: `${level} · ${t(`events.severity.${level}`)}`,
            }))}
            value={severity.map(String)}
            onChange={(values) => {
              update('severity', values)
            }}
            clearable
            w={260}
          />
          <TagsInput
            label={t('events.mnemonic')}
            placeholder={mnemonic.length ? undefined : t('events.mnemonicPlaceholder')}
            data={COMMON_MNEMONICS}
            value={mnemonic}
            onChange={(values) => {
              update(
                'mnemonic',
                values.map((value) => value.trim().replace(/^%/, '').toUpperCase()),
              )
            }}
            clearable
            w={320}
          />
          <Select
            label={t('filters.range')}
            data={RANGES.map((value) => ({ value, label: t(`filters.ranges.${value}`) }))}
            value={range}
            onChange={(value) => {
              update('range', value ? [value] : [])
            }}
            allowDeselect={false}
            w={160}
          />
        </Group>
      </Card>
      {events.isError && (
        <ProblemAlert error={events.error} onRetry={() => void events.refetch()} />
      )}
      {events.isPending && <Skeleton height={280} />}
      {events.data && total === 0 && (
        <EmptyState
          icon={IconMessageOff}
          title={t('events.empty.title')}
          body={t('events.empty.body')}
        />
      )}
      {events.data && total > 0 && (
        <Card withBorder padding={0}>
          <ScrollArea>
            <Table striped verticalSpacing={4} miw={1000} data-testid="events-table">
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>{t('events.columns.time')}</Table.Th>
                  <Table.Th>{t('events.columns.device')}</Table.Th>
                  <Table.Th>{t('events.columns.severity')}</Table.Th>
                  <Table.Th>{t('events.columns.mnemonic')}</Table.Th>
                  <Table.Th>{t('events.columns.message')}</Table.Th>
                  <Table.Th>{t('events.columns.source')}</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {events.data.items.map((event) => (
                  <Table.Tr key={`${event.id}-${event.received_at}`}>
                    <Table.Td style={{ whiteSpace: 'nowrap' }}>
                      <RelativeTime value={event.received_at} />
                    </Table.Td>
                    <Table.Td>
                      {event.device ? (
                        <Anchor component={Link} to={`/devices/${event.device.id}`}>
                          {event.device.hostname ?? event.device.mgmt_ip}
                        </Anchor>
                      ) : (
                        t('common.none')
                      )}
                    </Table.Td>
                    <Table.Td style={{ whiteSpace: 'nowrap' }}>
                      <SeverityBadge severity={event.severity} />
                    </Table.Td>
                    <Table.Td className="mono" style={{ whiteSpace: 'nowrap' }}>
                      {event.mnemonic ?? t('common.none')}
                    </Table.Td>
                    <Table.Td className="mono" style={{ whiteSpace: 'pre-wrap' }}>
                      {event.message}
                    </Table.Td>
                    <Table.Td className="mono">{event.source_ip}</Table.Td>
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
            const next = new URLSearchParams(params)
            next.set('page', String(value))
            setParams(next, { replace: true })
          }}
          aria-label={t('common.page')}
        />
      )}
    </Stack>
  )
}
