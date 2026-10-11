import {
  Alert,
  Button,
  Card,
  Grid,
  Group,
  Loader,
  SegmentedControl,
  Select,
  Skeleton,
  Stack,
  Text,
  Timeline,
  Title,
  UnstyledButton,
} from '@mantine/core'
import { useQueryClient } from '@tanstack/react-query'
import {
  IconArrowsDiff,
  IconBolt,
  IconCalendarTime,
  IconDeviceFloppy,
  IconEye,
  IconHandClick,
  IconInfoCircle,
  IconRobot,
  IconUser,
} from '@tabler/icons-react'
import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useSearchParams } from 'react-router'

import type { Schemas } from '../../api/client'
import {
  keys,
  useConfigChanges,
  useConfigDiff,
  useConfigVersion,
  useDeviceConfigs,
  useJob,
  useRefreshDevice,
} from '../../api/queries'
import { useCan } from '../../auth/context'
import { ProblemAlert } from '../../components/ProblemAlert'
import { RelativeTime } from '../../components/RelativeTime'
import { dateTime } from '../../lib/format'
import { OriginBadge, TriggerBadge } from './badges'
import { ChangesTable } from './ChangesTable'
import { ConfigViewer } from './ConfigViewer'
import { type DiffMode, DiffView } from './DiffView'

type Version = Schemas['ConfigVersion']

const BULLET = {
  scheduled: IconCalendarTime,
  change_event: IconBolt,
  manual: IconHandClick,
  pre_change: IconRobot,
  post_change: IconRobot,
} as const

function BackupButton({ device }: { device: Schemas['Device'] }) {
  const { t } = useTranslation()
  const client = useQueryClient()
  const refresh = useRefreshDevice(device.id)
  const [jobId, setJobId] = useState<string | null>(null)
  const job = useJob(jobId)
  const status = job.data?.status
  useEffect(() => {
    if (status === 'succeeded' || status === 'failed') {
      void client.invalidateQueries({ queryKey: keys.deviceConfigs(device.id) })
      void client.invalidateQueries({ queryKey: ['config-changes'] })
    }
  }, [status, client, device.id])
  const busy = refresh.isPending || status === 'queued' || status === 'running'
  return (
    <Group gap="xs">
      <div aria-live="polite">
        {status === 'succeeded' && (
          <Text size="sm" c="teal">
            {t('configs.backup.done')}
          </Text>
        )}
        {status === 'failed' && (
          <Text size="sm" c="red">
            {t('configs.backup.failed', { error: job.data?.error?.detail ?? '' })}
          </Text>
        )}
      </div>
      <Button
        variant="light"
        leftSection={busy ? <Loader size={14} /> : <IconDeviceFloppy size={16} aria-hidden />}
        disabled={busy || !device.is_managed}
        onClick={() => {
          refresh.mutate(['config'], {
            onSuccess: (ref) => {
              setJobId(ref.id)
            },
          })
        }}
      >
        {busy ? t('configs.backup.running') : t('configs.backup.button')}
      </Button>
    </Group>
  )
}

function VersionTimeline({
  versions,
  changes,
  selected,
  onSelect,
}: {
  versions: Version[]
  changes: Map<string, Schemas['ConfigChange']>
  selected: string | null
  onSelect: (id: string) => void
}) {
  const { t, i18n } = useTranslation()
  const active = versions.findIndex((v) => v.id === selected)
  return (
    <Timeline active={active} bulletSize={24} lineWidth={2} data-testid="config-timeline">
      {versions.map((version, index) => {
        const IconComponent = BULLET[version.trigger]
        const change = changes.get(version.id)
        const first = index === versions.length - 1
        return (
          <Timeline.Item
            key={version.id}
            bullet={<IconComponent size={13} aria-hidden />}
            title={
              <UnstyledButton
                onClick={() => {
                  onSelect(version.id)
                }}
                aria-current={version.id === selected ? 'true' : undefined}
                aria-label={t('configs.timeline.select', {
                  time: dateTime(version.collected_at, i18n.language),
                })}
              >
                <Text fw={version.id === selected ? 700 : 500} size="sm">
                  {dateTime(version.collected_at, i18n.language)}
                </Text>
              </UnstyledButton>
            }
          >
            <Stack gap={4} mt={2}>
              <Text size="xs" c="dimmed">
                <RelativeTime value={version.collected_at} />
              </Text>
              <Group gap={4}>
                <TriggerBadge trigger={version.trigger} />
                {first && (
                  <Text size="xs" c="dimmed">
                    {t('configs.timeline.first')}
                  </Text>
                )}
              </Group>
              {change && (
                <Group gap={4}>
                  <OriginBadge origin={change.origin} />
                  <Group gap={2}>
                    <IconUser size={12} aria-hidden />
                    <Text size="xs">{change.username ?? t('configs.timeline.unknownUser')}</Text>
                  </Group>
                </Group>
              )}
            </Stack>
          </Timeline.Item>
        )
      })}
    </Timeline>
  )
}

function VersionMeta({ version }: { version: Version }) {
  const { t } = useTranslation()
  return (
    <Group gap="md">
      <Text size="xs" c="dimmed">
        {t('configs.viewer.size', { size: version.size_bytes.toLocaleString() })}
      </Text>
      <Text size="xs" c="dimmed" className="mono" title={version.content_hash}>
        sha256 {version.content_hash.slice(0, 12)}
      </Text>
      <Text size="xs" c="dimmed" className="mono" title={version.git_commit}>
        git {version.git_commit.slice(0, 10)}
      </Text>
    </Group>
  )
}

/** The Config tab of a device: version timeline, redacted viewer, diffs and changes. */
export function ConfigTab({ device }: { device: Schemas['Device'] }) {
  const { t, i18n } = useTranslation()
  const canBackup = useCan('configs:backup')
  const [params, setParams] = useSearchParams()
  const versions = useDeviceConfigs(device.id)
  const changes = useConfigChanges({ device_id: device.id, limit: 200 })
  const items = useMemo(() => versions.data?.items ?? [], [versions.data])

  const set = (updates: Record<string, string | null>) => {
    const next = new URLSearchParams(params)
    for (const [key, value] of Object.entries(updates)) {
      if (value) next.set(key, value)
      else next.delete(key)
    }
    setParams(next, { replace: true })
  }

  const selected = params.get('version') ?? items[0]?.id ?? null
  const view = params.get('view') === 'diff' ? 'diff' : 'show'
  const mode: DiffMode = params.get('mode') === 'unified' ? 'unified' : 'split'
  const selectedIndex = items.findIndex((v) => v.id === selected)
  const previous = selectedIndex >= 0 ? (items[selectedIndex + 1]?.id ?? null) : null
  const from = params.get('from') ?? previous
  const to = params.get('to') ?? selected

  const byVersion = useMemo(
    () =>
      new Map(
        (changes.data?.items ?? []).flatMap((change) =>
          change.after_version_id ? [[change.after_version_id, change] as const] : [],
        ),
      ),
    [changes.data],
  )
  const content = useConfigVersion(view === 'show' ? selected : null)
  const diff = useConfigDiff(view === 'diff' ? from : null, view === 'diff' ? to : null)
  const options = items.map((version) => ({
    value: version.id,
    label: `${dateTime(version.collected_at, i18n.language)} · ${t(`enums.configTrigger.${version.trigger}`)}`,
  }))

  return (
    <Stack gap="md">
      <Card withBorder>
        <Group justify="space-between" mb="sm">
          <Title order={3} size="h4">
            {t('configs.history')}
            {versions.data && (
              <Text span c="dimmed" size="sm" ml="xs">
                {t('configs.versionCount', { count: versions.data.total })}
              </Text>
            )}
          </Title>
          {canBackup && <BackupButton device={device} />}
        </Group>
        <Alert variant="light" color="gray" icon={<IconInfoCircle size={18} />} mb="md">
          {t('configs.redaction.notice')}
        </Alert>
        {versions.isError && <ProblemAlert error={versions.error} />}
        {versions.isPending && <Skeleton height={240} />}
        {versions.data?.total === 0 && <Text c="dimmed">{t('configs.noVersions')}</Text>}
        {items.length > 0 && (
          <Grid gap="lg">
            <Grid.Col span={{ base: 12, md: 4, lg: 3 }}>
              <VersionTimeline
                versions={items}
                changes={byVersion}
                selected={selected}
                onSelect={(id) => {
                  set({ version: id, from: null, to: null })
                }}
              />
            </Grid.Col>
            <Grid.Col span={{ base: 12, md: 8, lg: 9 }}>
              <Stack gap="sm">
                <Group justify="space-between">
                  <SegmentedControl
                    value={view}
                    onChange={(value) => {
                      set({ view: value === 'diff' ? 'diff' : null })
                    }}
                    data={[
                      {
                        value: 'show',
                        label: (
                          <Group gap={4} wrap="nowrap">
                            <IconEye size={14} aria-hidden />
                            {t('configs.viewer.show')}
                          </Group>
                        ),
                      },
                      {
                        value: 'diff',
                        label: (
                          <Group gap={4} wrap="nowrap">
                            <IconArrowsDiff size={14} aria-hidden />
                            {t('configs.viewer.compare')}
                          </Group>
                        ),
                      },
                    ]}
                  />
                  {view === 'diff' && (
                    <SegmentedControl
                      size="xs"
                      value={mode}
                      aria-label={t('configs.diff.mode')}
                      onChange={(value) => {
                        set({ mode: value === 'unified' ? 'unified' : null })
                      }}
                      data={[
                        { value: 'split', label: t('configs.diff.split') },
                        { value: 'unified', label: t('configs.diff.unified') },
                      ]}
                    />
                  )}
                </Group>

                {view === 'show' && (
                  <>
                    {items[selectedIndex] && <VersionMeta version={items[selectedIndex]} />}
                    {content.isError && <ProblemAlert error={content.error} />}
                    {content.isPending && <Skeleton height={320} />}
                    {content.data && <ConfigViewer content={content.data.content} />}
                  </>
                )}

                {view === 'diff' && (
                  <>
                    <Group grow align="flex-end">
                      <Select
                        label={t('configs.diff.from')}
                        data={options}
                        value={from}
                        onChange={(value) => {
                          set({ from: value })
                        }}
                        allowDeselect={false}
                      />
                      <Select
                        label={t('configs.diff.to')}
                        data={options}
                        value={to}
                        onChange={(value) => {
                          set({ to: value })
                        }}
                        allowDeselect={false}
                      />
                    </Group>
                    {items.length < 2 && <Text c="dimmed">{t('configs.diff.needTwo')}</Text>}
                    {diff.isError && <ProblemAlert error={diff.error} />}
                    {diff.isFetching && !diff.data && <Skeleton height={240} />}
                    {diff.data && (
                      <DiffView
                        text={diff.data.unified_diff}
                        added={diff.data.added_lines}
                        removed={diff.data.removed_lines}
                        mode={mode}
                      />
                    )}
                  </>
                )}
              </Stack>
            </Grid.Col>
          </Grid>
        )}
      </Card>

      <Card withBorder>
        <Title order={3} size="h4" mb="sm">
          {t('configs.changes.title')}
        </Title>
        {changes.isError && <ProblemAlert error={changes.error} />}
        {changes.data?.total === 0 && <Text c="dimmed">{t('configs.changes.empty')}</Text>}
        {changes.data && changes.data.total > 0 && (
          <ChangesTable items={changes.data.items} showDevice={false} />
        )}
      </Card>
    </Stack>
  )
}
