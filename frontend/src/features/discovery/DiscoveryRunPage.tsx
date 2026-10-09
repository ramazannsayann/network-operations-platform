import {
  Accordion,
  Alert,
  Anchor,
  Badge,
  Card,
  Group,
  Loader,
  Paper,
  ScrollArea,
  SimpleGrid,
  Skeleton,
  Stack,
  Table,
  Text,
  Title,
} from '@mantine/core'
import { IconArrowLeft } from '@tabler/icons-react'
import { useTranslation } from 'react-i18next'
import { Link, useParams } from 'react-router'

import type { Schemas } from '../../api/client'
import { useDiscoveryRun } from '../../api/queries'
import { ProblemAlert } from '../../components/ProblemAlert'
import { RelativeTime } from '../../components/RelativeTime'
import { ItemStatusBadge, JobStatusBadge } from '../../components/StatusBadges'
import { groupItems } from './groups'

type Item = Schemas['DiscoveryRunItem']

function DeviceLink({ device }: { device: Schemas['DeviceRef'] | null | undefined }) {
  const { t } = useTranslation()
  if (!device) return <>{t('common.none')}</>
  return (
    <Anchor component={Link} to={`/devices/${device.id}`}>
      {device.hostname ?? device.mgmt_ip ?? device.id}
    </Anchor>
  )
}

function ItemTable({ items }: { items: Item[] }) {
  const { t } = useTranslation()
  // Known outcomes in the UI language; the API's own message stays in the tooltip.
  const note = (item: Item): string => {
    switch (item.status) {
      case 'duplicate':
        return t('discovery.run.duplicateNote', {
          device: item.device?.hostname ?? item.device?.mgmt_ip ?? '?',
        })
      case 'auth_failed':
        return t('discovery.run.authFailedNote', { attempts: item.attempts })
      case 'unreachable':
        return item.error ?? t('discovery.run.unreachableNote')
      default:
        return item.error ?? item.platform ?? ''
    }
  }
  return (
    <ScrollArea>
      <Table verticalSpacing={4} miw={760}>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>{t('discovery.run.columns.address')}</Table.Th>
            <Table.Th>{t('discovery.run.columns.device')}</Table.Th>
            <Table.Th>{t('discovery.run.columns.hop')}</Table.Th>
            <Table.Th>{t('discovery.run.columns.seenFrom')}</Table.Th>
            <Table.Th>{t('discovery.run.columns.attempts')}</Table.Th>
            <Table.Th>{t('discovery.run.columns.note')}</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {items.map((item, index) => (
            <Table.Tr key={`${item.address ?? item.neighbor_name ?? ''}-${String(index)}`}>
              <Table.Td className="mono">{item.address ?? t('common.none')}</Table.Td>
              <Table.Td>
                <Group gap={6} wrap="nowrap">
                  <DeviceLink device={item.device} />
                  {item.is_new && (
                    <Badge size="xs" variant="light">
                      {t('discovery.run.newDevice')}
                    </Badge>
                  )}
                </Group>
              </Table.Td>
              <Table.Td>{item.hop}</Table.Td>
              <Table.Td>
                {item.seen_from ? (
                  <>
                    <DeviceLink device={item.seen_from} />{' '}
                    <Text span size="xs" c="dimmed" className="mono">
                      {item.local_interface}
                    </Text>
                  </>
                ) : (
                  t('enums.discoverySource.seed')
                )}
              </Table.Td>
              <Table.Td>{item.attempts}</Table.Td>
              <Table.Td>
                <Text size="sm" c={item.error ? 'red' : 'dimmed'} title={item.error ?? undefined}>
                  {note(item)}
                </Text>
              </Table.Td>
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </ScrollArea>
  )
}

export function DiscoveryRunPage() {
  const { t } = useTranslation()
  const { runId = '' } = useParams()
  const run = useDiscoveryRun(runId)

  const back = (
    <Anchor component={Link} to="/discovery" size="sm">
      <Group gap={4}>
        <IconArrowLeft size={16} aria-hidden />
        {t('discovery.run.back')}
      </Group>
    </Anchor>
  )
  if (run.isError)
    return (
      <Stack>
        {back}
        <ProblemAlert error={run.error} onRetry={() => void run.refetch()} />
      </Stack>
    )
  if (!run.data) return <Skeleton height={320} />
  const r = run.data
  const active = r.status === 'queued' || r.status === 'running'
  const groups = groupItems(r.items)

  return (
    <Stack gap="md">
      {back}
      <Group justify="space-between">
        <Title order={2}>{t('discovery.run.title')}</Title>
        <JobStatusBadge status={r.status} />
      </Group>
      {active && (
        <Alert color="blue" variant="light" icon={<Loader size={16} />} aria-live="polite">
          {t('discovery.run.running')}
        </Alert>
      )}
      {r.status === 'failed' && (
        <Alert color="red" variant="light">
          {t('discovery.run.failed', {
            error: r.errors[0]?.message ?? '',
          })}
        </Alert>
      )}

      <SimpleGrid cols={{ base: 2, sm: 5 }}>
        {(['found', 'skipped', 'errors', 'scanned', 'queued'] as const).map((key) => (
          <Paper key={key} withBorder p="sm" ta="center">
            <Text size="xl" fw={700} aria-live="polite">
              {r.progress[key]}
            </Text>
            <Text size="xs" c="dimmed">
              {t(`discovery.run.progress.${key}`)}
            </Text>
          </Paper>
        ))}
      </SimpleGrid>

      <Card withBorder>
        <SimpleGrid cols={{ base: 1, sm: 2, md: 4 }}>
          <div>
            <Text size="xs" c="dimmed">
              {t('discovery.run.seeds')}
            </Text>
            <Text className="mono">{r.request.seeds.join(', ')}</Text>
          </div>
          <div>
            <Text size="xs" c="dimmed">
              {t('discovery.run.subnets')}
            </Text>
            <Text className="mono">{r.request.allowed_subnets.join(', ')}</Text>
          </div>
          <div>
            <Text size="xs" c="dimmed">
              {t('discovery.run.started')}
            </Text>
            <RelativeTime value={r.started_at} />
          </div>
          <div>
            <Text size="xs" c="dimmed">
              {t('discovery.run.finished')}
            </Text>
            <RelativeTime value={r.finished_at} />
          </div>
        </SimpleGrid>
      </Card>

      {groups.length === 0 ? (
        <Text c="dimmed">{t('discovery.run.noItems')}</Text>
      ) : (
        <Accordion multiple defaultValue={groups.map(([status]) => status)} variant="separated">
          {groups.map(([status, items]) => (
            <Accordion.Item key={status} value={status}>
              <Accordion.Control>
                <Group gap="sm">
                  <ItemStatusBadge status={status} />
                  <Text size="sm" c="dimmed">
                    {items.length}
                  </Text>
                </Group>
              </Accordion.Control>
              <Accordion.Panel>
                <ItemTable items={items} />
              </Accordion.Panel>
            </Accordion.Item>
          ))}
        </Accordion>
      )}
    </Stack>
  )
}
