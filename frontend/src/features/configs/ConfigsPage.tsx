import {
  Anchor,
  Badge,
  Button,
  Card,
  Group,
  Pagination,
  ScrollArea,
  Skeleton,
  Stack,
  Table,
  Text,
  TextInput,
  Title,
} from '@mantine/core'
import { useDebouncedValue } from '@mantine/hooks'
import { IconFileOff, IconHistory, IconSearch, IconUserExclamation } from '@tabler/icons-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useSearchParams } from 'react-router'

import { useConfigBackups } from '../../api/queries'
import { EmptyState } from '../../components/EmptyState'
import { ProblemAlert } from '../../components/ProblemAlert'
import { RelativeTime } from '../../components/RelativeTime'
import { CollectionStatusBadge } from '../../components/StatusBadges'

const PAGE_SIZE = 25
const RECENT_DAYS = 7

/** The Config page: every managed device's last backup, versions and recent changes. */
export function ConfigsPage() {
  const { t } = useTranslation()
  const [params, setParams] = useSearchParams()
  const [search, setSearch] = useState(params.get('q') ?? '')
  const [q] = useDebouncedValue(search, 300)
  const page = Number(params.get('page') ?? '1') || 1
  const backups = useConfigBackups({
    days: RECENT_DAYS,
    limit: PAGE_SIZE,
    offset: (page - 1) * PAGE_SIZE,
    ...(q ? { q } : {}),
  })
  const total = backups.data?.total ?? 0

  return (
    <Stack gap="md">
      <Group justify="space-between">
        <Stack gap={0}>
          <Title order={2}>{t('configs.title')}</Title>
          <Text c="dimmed" size="sm">
            {t('configs.subtitle')}
          </Text>
        </Stack>
        <Button
          component={Link}
          to="/config-changes"
          variant="light"
          leftSection={<IconHistory size={16} aria-hidden />}
        >
          {t('nav.configChanges')}
        </Button>
      </Group>
      <Card withBorder padding="sm">
        <TextInput
          label={t('configs.search')}
          placeholder={t('devices.searchPlaceholder')}
          leftSection={<IconSearch size={16} aria-hidden />}
          value={search}
          onChange={(event) => {
            setSearch(event.currentTarget.value)
          }}
          maw={360}
        />
      </Card>
      {backups.isError && (
        <ProblemAlert error={backups.error} onRetry={() => void backups.refetch()} />
      )}
      {backups.isPending && <Skeleton height={280} />}
      {backups.data && total === 0 && (
        <EmptyState
          icon={IconFileOff}
          title={t('configs.empty.title')}
          body={t('configs.empty.body')}
        />
      )}
      {backups.data && total > 0 && (
        <Card withBorder padding={0}>
          <ScrollArea>
            <Table striped highlightOnHover verticalSpacing="xs" miw={900}>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>{t('configs.columns.device')}</Table.Th>
                  <Table.Th>{t('configs.columns.lastBackup')}</Table.Th>
                  <Table.Th>{t('configs.columns.status')}</Table.Th>
                  <Table.Th>{t('configs.columns.versions')}</Table.Th>
                  <Table.Th>{t('configs.columns.lastChange')}</Table.Th>
                  <Table.Th>{t('configs.columns.recentExternal', { days: RECENT_DAYS })}</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {backups.data.items.map((row) => (
                  <Table.Tr key={row.device.id}>
                    <Table.Td>
                      <Anchor component={Link} to={`/devices/${row.device.id}?tab=config`} fw={500}>
                        {row.device.hostname ?? row.device.mgmt_ip}
                      </Anchor>
                      <Text size="xs" c="dimmed" className="mono">
                        {row.device.mgmt_ip}
                      </Text>
                    </Table.Td>
                    <Table.Td>
                      <RelativeTime value={row.last_backup_at} />
                    </Table.Td>
                    <Table.Td>
                      {row.last_backup_status ? (
                        <CollectionStatusBadge status={row.last_backup_status} />
                      ) : (
                        <Text c="dimmed">{t('configs.neverBackedUp')}</Text>
                      )}
                    </Table.Td>
                    <Table.Td>{row.version_count}</Table.Td>
                    <Table.Td>
                      <RelativeTime value={row.last_change_at} />
                    </Table.Td>
                    <Table.Td>
                      {row.recent_external_changes > 0 ? (
                        <Badge
                          color="violet"
                          variant="light"
                          leftSection={<IconUserExclamation size={12} aria-hidden />}
                        >
                          {t('configs.externalCount', { count: row.recent_external_changes })}
                        </Badge>
                      ) : (
                        <Text c="dimmed">{t('common.none')}</Text>
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
