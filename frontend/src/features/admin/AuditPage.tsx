import {
  Badge,
  Card,
  Code,
  Group,
  Pagination,
  ScrollArea,
  SegmentedControl,
  Select,
  Skeleton,
  Stack,
  Table,
  Text,
  TextInput,
  Title,
} from '@mantine/core'
import { useDebouncedValue } from '@mantine/hooks'
import { IconBan, IconCheck, IconX } from '@tabler/icons-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import type { Schemas } from '../../api/client'
import { type AuditQuery, useAudit } from '../../api/queries'
import { ProblemAlert } from '../../components/ProblemAlert'
import { RelativeTime } from '../../components/RelativeTime'
import { parseRange, RANGES, rangeStart } from '../configs/timeRange'

const PAGE_SIZE = 50
const ACTIONS = [
  'auth.*',
  'auth.login',
  'auth.lockout',
  'auth.refresh.reuse',
  'auth.mfa.*',
  'user.*',
  'credentials.*',
  'access.denied',
  'discovery.start',
  'device.refresh',
  'config.backup',
  'topology.layout.save',
]

const OUTCOME = {
  success: { color: 'teal', icon: IconCheck },
  denied: { color: 'orange', icon: IconBan },
  failed: { color: 'red', icon: IconX },
} as const

function OutcomeBadge({ outcome }: { outcome: Schemas['AuditOutcome'] }) {
  const { t } = useTranslation()
  const look = OUTCOME[outcome]
  const IconComponent = look.icon
  return (
    <Badge
      color={look.color}
      variant="light"
      leftSection={<IconComponent size={12} />}
      style={{ overflow: 'visible' }}
    >
      {t(`enums.auditOutcome.${outcome}`)}
    </Badge>
  )
}

/** Denetim kaydı: the append-only audit log, filterable. */
export function AuditPage() {
  const { t } = useTranslation()
  const [actor, setActor] = useState('')
  const [debouncedActor] = useDebouncedValue(actor, 400)
  const [action, setAction] = useState<string | null>(null)
  const [outcome, setOutcome] = useState('all')
  const [range, setRange] = useState(parseRange(null, '7d'))
  const [page, setPage] = useState(1)
  const from = rangeStart(range)
  const query: AuditQuery = {
    limit: PAGE_SIZE,
    offset: (page - 1) * PAGE_SIZE,
    ...(debouncedActor ? { actor: debouncedActor } : {}),
    ...(action ? { action: [action] } : {}),
    ...(outcome !== 'all' ? { outcome: [outcome as Schemas['AuditOutcome']] } : {}),
    ...(from ? { from } : {}),
  }
  const audit = useAudit(query)
  const total = audit.data?.total ?? 0

  return (
    <Stack gap="md">
      <Group justify="space-between">
        <Stack gap={0}>
          <Title order={2}>{t('admin.audit.title')}</Title>
          <Text c="dimmed" size="sm">
            {t('admin.audit.subtitle')}
          </Text>
        </Stack>
        {audit.data && <Text c="dimmed">{t('admin.audit.count', { count: total })}</Text>}
      </Group>
      <Card withBorder padding="sm">
        <Group gap="sm" align="flex-end">
          <TextInput
            label={t('admin.audit.actor')}
            placeholder={t('admin.audit.actorPlaceholder')}
            value={actor}
            onChange={(event) => {
              setActor(event.currentTarget.value)
              setPage(1)
            }}
            w={180}
          />
          <Select
            label={t('admin.audit.action')}
            placeholder={t('common.all')}
            data={ACTIONS}
            value={action}
            onChange={(value) => {
              setAction(value)
              setPage(1)
            }}
            clearable
            searchable
            w={220}
          />
          <Stack gap={4}>
            <Text size="sm" fw={500}>
              {t('admin.audit.outcome')}
            </Text>
            <SegmentedControl
              value={outcome}
              onChange={(value) => {
                setOutcome(value)
                setPage(1)
              }}
              data={[
                { value: 'all', label: t('common.all') },
                { value: 'success', label: t('enums.auditOutcome.success') },
                { value: 'denied', label: t('enums.auditOutcome.denied') },
                { value: 'failed', label: t('enums.auditOutcome.failed') },
              ]}
            />
          </Stack>
          <Select
            label={t('filters.range')}
            data={RANGES.map((value) => ({ value, label: t(`filters.ranges.${value}`) }))}
            value={range}
            onChange={(value) => {
              setRange(parseRange(value, '7d'))
              setPage(1)
            }}
            allowDeselect={false}
            w={160}
          />
        </Group>
      </Card>
      {audit.isError && <ProblemAlert error={audit.error} />}
      {audit.isPending && <Skeleton height={300} />}
      {audit.data && (
        <Card withBorder padding={0}>
          <ScrollArea>
            <Table verticalSpacing={4} striped miw={1100} data-testid="audit-table">
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>{t('admin.audit.when')}</Table.Th>
                  <Table.Th>{t('admin.audit.actor')}</Table.Th>
                  <Table.Th>{t('admin.audit.address')}</Table.Th>
                  <Table.Th>{t('admin.audit.action')}</Table.Th>
                  <Table.Th>{t('admin.audit.target')}</Table.Th>
                  <Table.Th>{t('admin.audit.outcome')}</Table.Th>
                  <Table.Th>{t('admin.audit.details')}</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {audit.data.items.map((entry) => (
                  <Table.Tr key={entry.id}>
                    <Table.Td style={{ whiteSpace: 'nowrap' }}>
                      <RelativeTime value={entry.at} />
                    </Table.Td>
                    <Table.Td>
                      {entry.actor ? (
                        <Text size="sm" className="mono">
                          {entry.actor.username ?? entry.actor.id.slice(0, 8)}
                        </Text>
                      ) : (
                        <Text size="sm" c="dimmed">
                          {t('admin.audit.noActor')}
                        </Text>
                      )}
                    </Table.Td>
                    <Table.Td className="mono">{entry.actor_ip ?? t('common.none')}</Table.Td>
                    <Table.Td className="mono" style={{ whiteSpace: 'nowrap' }}>
                      {entry.action}
                    </Table.Td>
                    <Table.Td>
                      {entry.target_type ? (
                        <Text size="xs">
                          {entry.target_type} <span className="mono">{entry.target_id}</span>
                        </Text>
                      ) : (
                        t('common.none')
                      )}
                    </Table.Td>
                    <Table.Td style={{ whiteSpace: 'nowrap' }}>
                      <OutcomeBadge outcome={entry.outcome} />
                    </Table.Td>
                    <Table.Td maw={380}>
                      {Object.keys(entry.details).length > 0 && (
                        <Code style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
                          {JSON.stringify(entry.details)}
                        </Code>
                      )}
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
          onChange={setPage}
          aria-label={t('common.page')}
        />
      )}
    </Stack>
  )
}
