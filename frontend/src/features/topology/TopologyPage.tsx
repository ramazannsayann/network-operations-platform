import {
  ActionIcon,
  Alert,
  Anchor,
  Badge,
  Button,
  Card,
  Collapse,
  Drawer,
  Group,
  List,
  MultiSelect,
  Paper,
  ScrollArea,
  SegmentedControl,
  Select,
  SimpleGrid,
  Stack,
  Switch,
  Text,
  Title,
  Tooltip,
  UnstyledButton,
  useComputedColorScheme,
} from '@mantine/core'
import { DateTimePicker } from '@mantine/dates'
import { useViewportSize } from '@mantine/hooks'
import {
  IconArrowsMaximize,
  IconClockHour4,
  IconDeviceFloppy,
  IconExternalLink,
  IconHistory,
  IconLayoutGrid,
  IconRadar,
  IconSearch,
  IconTopologyStar3,
  IconX,
} from '@tabler/icons-react'
import dayjs from 'dayjs'
import { useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'

import type { Schemas } from '../../api/client'
import {
  type Layer,
  type TopologyQuery,
  useLayout,
  useLocations,
  useSaveLayout,
  useTopology,
  useTopologyChanges,
} from '../../api/queries'
import { EmptyState } from '../../components/EmptyState'
import { ProblemAlert } from '../../components/ProblemAlert'
import { RelativeTime } from '../../components/RelativeTime'
import { ManagementStatusBadge } from '../../components/StatusBadges'
import { CytoscapeMap, type MapController } from './CytoscapeMap'
import {
  layoutByRole,
  MAP_DEVICE_TYPES,
  mergePositions,
  shortPort,
  type Topology,
  toElements,
  withoutManagementSubnets,
  withStatusCaptions,
} from './elements'
import { NODE_ICONS } from './icons'

const ROLES: Schemas['DeviceRole'][] = ['edge', 'core', 'distribution', 'access', 'unknown']
/** DateTimePicker values: local time as "YYYY-MM-DD HH:mm:ss". */
const PICKER_FORMAT = 'YYYY-MM-DD HH:mm:ss'

function timePresets(t: (key: string) => string) {
  const now = dayjs()
  return [
    { value: null, label: t('topology.presets.now') },
    {
      value: now.subtract(15, 'minute').format(PICKER_FORMAT),
      label: t('topology.presets.minutes15'),
    },
    { value: now.subtract(1, 'hour').format(PICKER_FORMAT), label: t('topology.presets.hour1') },
    { value: now.subtract(1, 'day').format(PICKER_FORMAT), label: t('topology.presets.yesterday') },
  ]
}

function NodePanel({
  topology,
  nodeId,
  onClose,
}: {
  topology: Topology
  nodeId: string
  onClose: () => void
}) {
  const { t } = useTranslation()
  const node = topology.nodes.find((candidate) => candidate.id === nodeId)
  if (!node) return null
  const labels = new Map(topology.nodes.map((candidate) => [candidate.id, candidate.label]))
  const edges = topology.edges.filter((edge) => edge.source === nodeId || edge.target === nodeId)
  const line = (edge: Schemas['TopologyEdge']): string => {
    const outgoing = edge.source === nodeId
    if (edge.kind === 'subnet_member') {
      const port = edge.source_interface ? shortPort(edge.source_interface.name) : ''
      return outgoing
        ? `${port} ${edge.address ?? ''} → ${labels.get(edge.target) ?? '?'}`
        : `${labels.get(edge.source) ?? '?'} ${port} ${edge.address ?? ''}`
    }
    const local = outgoing ? edge.source_interface : edge.target_interface
    const remote = outgoing ? edge.target_interface : edge.source_interface
    return `${shortPort(local?.name)} → ${labels.get(outgoing ? edge.target : edge.source) ?? '?'} ${shortPort(remote?.name)}`
  }
  return (
    <Paper withBorder p="md" h="100%" component="aside" aria-label={t('topology.panel.title')}>
      <Group justify="space-between" mb="xs" wrap="nowrap">
        <Title order={3} size="h4">
          {node.label}
        </Title>
        <ActionIcon variant="subtle" onClick={onClose} aria-label={t('common.close')}>
          <IconX size={18} />
        </ActionIcon>
      </Group>
      <Stack gap="xs">
        {node.kind === 'device' ? (
          <>
            <Group gap="xs">
              {node.management_status && <ManagementStatusBadge status={node.management_status} />}
              <Badge variant="outline">
                {t(`enums.deviceType.${node.device_type ?? 'unknown'}`)}
              </Badge>
              <Badge variant="outline">{t(`enums.role.${node.role ?? 'unknown'}`)}</Badge>
            </Group>
            <Text size="sm">
              <Text span c="dimmed">
                {t('device.mgmtIp')}:{' '}
              </Text>
              <span className="mono">{node.mgmt_ip ?? t('common.none')}</span>
            </Text>
            <Text size="sm">
              <Text span c="dimmed">
                {t('device.model')}:{' '}
              </Text>
              {node.model ?? t('common.unknown')}
            </Text>
            {node.device_id && (
              <Anchor component={Link} to={`/devices/${node.device_id}`} size="sm">
                <Group gap={4}>
                  {t('topology.panel.openDevice')}
                  <IconExternalLink size={14} aria-hidden />
                </Group>
              </Anchor>
            )}
          </>
        ) : (
          <Text size="sm">
            <Text span c="dimmed">
              {t('topology.panel.gateways')}:{' '}
            </Text>
            <span className="mono">
              {node.gateway_ips.length > 0 ? node.gateway_ips.join(', ') : t('common.none')}
            </span>
          </Text>
        )}
        <ScrollArea.Autosize mah={360}>
          <List size="sm" spacing={4}>
            {edges.map((edge) => (
              <List.Item key={edge.id}>
                <span className="mono">{line(edge)}</span>
                {edge.kind === 'etherchannel' && (
                  <Text span size="xs" c="dimmed">
                    {' '}
                    ({t('topology.panel.members')}:{' '}
                    {edge.members
                      .map((member) =>
                        shortPort(
                          (edge.source === nodeId
                            ? member.source_interface
                            : member.target_interface
                          ).name,
                        ),
                      )
                      .join(', ')}
                    )
                  </Text>
                )}
                {edge.hsrp_state && (
                  <Badge
                    size="xs"
                    ml={4}
                    variant={edge.hsrp_state === 'active' ? 'filled' : 'light'}
                    color="teal"
                  >
                    HSRP {edge.hsrp_state}
                  </Badge>
                )}
              </List.Item>
            ))}
          </List>
        </ScrollArea.Autosize>
      </Stack>
    </Paper>
  )
}

function ChangesDrawer({ opened, onClose }: { opened: boolean; onClose: () => void }) {
  const { t } = useTranslation()
  const [since, setSince] = useState<string | null>(() =>
    dayjs().subtract(7, 'day').format(PICKER_FORMAT),
  )
  const sinceIso = useMemo(() => dayjs(since ?? undefined).toISOString(), [since])
  const changes = useTopologyChanges(sinceIso)
  const data = changes.data
  const link = (change: Schemas['LinkChange']) =>
    `${change.a.device.hostname ?? '?'} ${shortPort(change.a.interface.name)} ↔ ${change.b.device.hostname ?? '?'} ${shortPort(change.b.interface.name)}`
  const sections: [string, { key: string; text: string; at: string }[]][] = data
    ? [
        [
          'topology.changesPanel.addedDevices',
          data.added_devices.map((c) => ({
            key: c.device.id,
            text: c.device.hostname ?? c.device.mgmt_ip ?? '?',
            at: c.at,
          })),
        ],
        [
          'topology.changesPanel.removedDevices',
          data.removed_devices.map((c) => ({
            key: c.device.id,
            text: c.device.hostname ?? c.device.mgmt_ip ?? '?',
            at: c.at,
          })),
        ],
        [
          'topology.changesPanel.addedLinks',
          data.added_links.map((c) => ({ key: c.link_id, text: link(c), at: c.at })),
        ],
        [
          'topology.changesPanel.removedLinks',
          data.removed_links.map((c) => ({ key: c.link_id, text: link(c), at: c.at })),
        ],
      ]
    : []
  const empty = sections.every(([, items]) => items.length === 0)
  return (
    <Drawer
      opened={opened}
      onClose={onClose}
      position="right"
      title={t('topology.changesPanel.title')}
      size="md"
    >
      <Stack gap="md">
        <DateTimePicker
          label={t('topology.changesPanel.since')}
          valueFormat={t('formats.dateTime')}
          value={since}
          onChange={setSince}
          maxDate={dayjs().format(PICKER_FORMAT)}
        />
        {changes.isError && <ProblemAlert error={changes.error} />}
        {data && empty && <Text c="dimmed">{t('topology.changesPanel.none')}</Text>}
        {sections.map(([title, items]) =>
          items.length === 0 ? null : (
            <div key={title}>
              <Title order={4} size="h5" mb={4}>
                {t(title)} <Badge size="sm">{items.length}</Badge>
              </Title>
              <List size="sm" spacing={2}>
                {items.map((item) => (
                  <List.Item key={item.key}>
                    <span className="mono">{item.text}</span>{' '}
                    <Text span size="xs" c="dimmed">
                      <RelativeTime value={item.at} />
                    </Text>
                  </List.Item>
                ))}
              </List>
            </div>
          ),
        )}
        <Text size="xs" c="dimmed">
          {t('topology.changesPanel.note')}
        </Text>
      </Stack>
    </Drawer>
  )
}

function Legend({ layer }: { layer: Layer }) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  const states = ['managed', 'outOfScope', 'endpoint', 'authFailed', 'unreachable']
  const links =
    layer === 'l2' ? ['etherchannel'] : ['hsrpActive', 'hsrpStandby', 'member', 'subnet']
  return (
    <Paper
      withBorder
      shadow="xs"
      p="xs"
      style={{ position: 'absolute', left: 8, bottom: 8, zIndex: 2, maxWidth: 420, opacity: 0.96 }}
    >
      <UnstyledButton
        onClick={() => {
          setOpen((value) => !value)
        }}
        aria-expanded={open}
      >
        <Text size="xs" fw={600}>
          {t('topology.legend.title')} {open ? '▾' : '▸'}
        </Text>
      </UnstyledButton>
      <Collapse expanded={open}>
        <Stack gap={6} mt={6}>
          <div>
            <Text size="xs" fw={600}>
              {t('topology.legend.types')}
            </Text>
            <SimpleGrid cols={3} spacing={4} verticalSpacing={2}>
              {[...MAP_DEVICE_TYPES, 'unknown'].map((type) => {
                const IconComponent = NODE_ICONS[type] ?? IconTopologyStar3
                return (
                  <Group key={type} gap={4} wrap="nowrap">
                    <IconComponent size={14} aria-hidden />
                    <Text size="xs">{t(`enums.deviceType.${type}`)}</Text>
                  </Group>
                )
              })}
            </SimpleGrid>
          </div>
          <div>
            <Text size="xs" fw={600}>
              {t('topology.legend.states')}
            </Text>
            {states.map((item) => (
              <Text key={item} size="xs" c="dimmed">
                {t(`topology.legend.${item}`)}
              </Text>
            ))}
          </div>
          <div>
            <Text size="xs" fw={600}>
              {t('topology.legend.links')}
            </Text>
            {links.map((item) => (
              <Text key={item} size="xs" c="dimmed">
                {t(`topology.legend.${item}`)}
              </Text>
            ))}
            <Text size="xs" c="dimmed" fs="italic">
              {t('topology.legend.hover')}
            </Text>
          </div>
        </Stack>
      </Collapse>
    </Paper>
  )
}

export function TopologyPage() {
  const { t } = useTranslation()
  const scheme = useComputedColorScheme('light')
  const viewport = useViewportSize()
  const map = useRef<MapController>(null)
  const [layer, setLayer] = useState<Layer>('l2')
  const [roles, setRoles] = useState<string[]>([])
  const [location, setLocation] = useState<string | null>(null)
  const [at, setAt] = useState<string | null>(null)
  const [showManagement, setShowManagement] = useState(true)
  const [selected, setSelected] = useState<string | null>(null)
  const [changesOpen, setChangesOpen] = useState(false)
  const [notice, setNotice] = useState('')

  const query: TopologyQuery = {
    layer,
    ...(roles.length > 0 ? { role: roles as Schemas['DeviceRole'][] } : {}),
    ...(location ? { location_id: location } : {}),
    ...(at ? { at: dayjs(at).toISOString() } : {}),
  }
  const topology = useTopology(query)
  const layout = useLayout(layer)
  const saveLayout = useSaveLayout(layer)
  const locations = useLocations()

  const elements = useMemo(() => {
    if (!topology.data) return { nodes: [], edges: [] }
    const all = withStatusCaptions(toElements(topology.data), (status) =>
      t(`topology.caption.${status}`),
    )
    return layer === 'l3' && !showManagement ? withoutManagementSubnets(all) : all
  }, [topology.data, t, layer, showManagement])
  // The canvas's shape (rounded, so a resize does not re-run the layout for every pixel).
  const aspect = Math.round(((viewport.width - 300) / Math.max(1, viewport.height - 300)) * 4) / 4
  const positions = useMemo(
    () =>
      mergePositions(
        layoutByRole(elements, Math.max(1, Math.min(aspect || 2, 3))),
        layout.data?.positions ?? [],
      ),
    [elements, layout.data, aspect],
  )
  const nodeCount = elements.nodes.length
  const edgeCount = elements.edges.length
  const summary = t('topology.summary', { nodes: nodeCount, edges: edgeCount })
  const filtered = roles.length > 0 || location !== null || at !== null
  const hasManagementSubnets = (topology.data?.nodes ?? []).some((node) => node.management_subnet)

  const searchData = elements.nodes.map(({ data }) => ({
    value: data.id,
    label: data.mgmtIp ? `${data.label} (${data.mgmtIp})` : data.label,
  }))

  return (
    <Stack gap="sm" h="calc(100vh - 92px)">
      <Group justify="space-between" wrap="nowrap">
        <Title order={2}>{t('topology.title')}</Title>
        <Text c="dimmed" size="sm" aria-live="polite" data-testid="topology-summary">
          {topology.data ? summary : ''}
        </Text>
      </Group>

      <Card withBorder padding="sm">
        <Group gap="sm" align="flex-end">
          <SegmentedControl
            aria-label={t('topology.layer')}
            value={layer}
            onChange={(value) => {
              setLayer(value)
              setSelected(null)
            }}
            data={[
              { value: 'l2', label: t('topology.l2') },
              { value: 'l3', label: t('topology.l3') },
            ]}
          />
          <Select
            label={t('topology.search')}
            placeholder={t('topology.searchPlaceholder')}
            leftSection={<IconSearch size={16} aria-hidden />}
            data={searchData}
            searchable
            clearable
            value={selected}
            onChange={(value) => {
              setSelected(value)
              if (value) map.current?.focus(value)
            }}
            w={220}
          />
          <MultiSelect
            label={t('topology.role')}
            placeholder={t('common.all')}
            data={ROLES.map((role) => ({ value: role, label: t(`enums.role.${role}`) }))}
            value={roles}
            onChange={setRoles}
            clearable
            w={200}
          />
          <Select
            label={t('topology.location')}
            placeholder={t('common.all')}
            data={(locations.data?.items ?? []).map((item) => ({
              value: item.id,
              label: item.path,
            }))}
            value={location}
            onChange={setLocation}
            clearable
            searchable
            w={170}
          />
          <DateTimePicker
            label={t('topology.at')}
            placeholder={t('topology.now')}
            leftSection={<IconClockHour4 size={16} aria-hidden />}
            valueFormat={t('formats.dateTime')}
            value={at}
            onChange={setAt}
            presets={timePresets(t)}
            maxDate={dayjs().format(PICKER_FORMAT)}
            clearable
            w={230}
          />
          {layer === 'l3' && hasManagementSubnets && (
            <Switch
              label={t('topology.management')}
              title={t('topology.managementHelp')}
              checked={showManagement}
              onChange={(event) => {
                setShowManagement(event.currentTarget.checked)
              }}
              mb={8}
            />
          )}
          <Group gap="xs" ml="auto">
            <Tooltip label={t('topology.saveLayout')}>
              <Button
                variant="default"
                leftSection={<IconDeviceFloppy size={16} aria-hidden />}
                loading={saveLayout.isPending}
                disabled={nodeCount === 0}
                onClick={() => {
                  saveLayout.mutate(map.current?.positions() ?? [], {
                    onSuccess: () => {
                      setNotice(t('topology.layoutSaved'))
                    },
                  })
                }}
              >
                {t('topology.saveLayout')}
              </Button>
            </Tooltip>
            <Button
              variant="default"
              leftSection={<IconLayoutGrid size={16} aria-hidden />}
              disabled={nodeCount === 0}
              onClick={() => {
                saveLayout.mutate([], {
                  onSuccess: () => {
                    setNotice(t('topology.layoutReset'))
                  },
                })
              }}
            >
              {t('topology.autoLayout')}
            </Button>
            <ActionIcon
              variant="default"
              size="lg"
              onClick={() => map.current?.fit()}
              aria-label={t('topology.fit')}
              title={t('topology.fit')}
            >
              <IconArrowsMaximize size={16} aria-hidden />
            </ActionIcon>
            <Button
              variant="light"
              leftSection={<IconHistory size={16} aria-hidden />}
              onClick={() => {
                setChangesOpen(true)
              }}
            >
              {t('topology.changes')}
            </Button>
          </Group>
        </Group>
        {notice && (
          <Text size="xs" c="teal" mt={4} aria-live="polite">
            {notice}
          </Text>
        )}
      </Card>

      {at && (
        <Alert
          color="violet"
          variant="filled"
          icon={<IconHistory aria-hidden />}
          py="xs"
          data-testid="historic-banner"
        >
          <Group justify="space-between" wrap="nowrap">
            <Text fw={600} size="sm">
              {t('topology.historicBanner', { time: dayjs(at).format(t('formats.dateTime')) })}
            </Text>
            <Button
              size="xs"
              variant="white"
              color="violet"
              onClick={() => {
                setAt(null)
              }}
            >
              {t('topology.backToNow')}
            </Button>
          </Group>
        </Alert>
      )}

      {topology.isError && (
        <ProblemAlert error={topology.error} onRetry={() => void topology.refetch()} />
      )}
      {saveLayout.isError && <ProblemAlert error={saveLayout.error} />}

      {topology.data && nodeCount === 0 ? (
        <EmptyState
          icon={filtered ? IconTopologyStar3 : IconRadar}
          title={t('topology.empty.title')}
          body={filtered ? t('topology.empty.filtered') : t('topology.empty.body')}
          action={
            filtered ? undefined : (
              <Button component={Link} to="/discovery" leftSection={<IconRadar size={16} />}>
                {t('devices.empty.action')}
              </Button>
            )
          }
        />
      ) : (
        <Group align="stretch" gap="sm" wrap="nowrap" style={{ flex: 1, minHeight: 0 }}>
          <Card withBorder padding={0} style={{ flex: 1, minWidth: 0, position: 'relative' }}>
            <Legend layer={layer} />
            <CytoscapeMap
              ref={map}
              elements={elements}
              positions={positions}
              scheme={scheme}
              selected={selected}
              onSelect={setSelected}
              label={summary}
            />
          </Card>
          {selected && topology.data && (
            <div style={{ width: 320, flexShrink: 0 }}>
              <NodePanel
                topology={topology.data}
                nodeId={selected}
                onClose={() => {
                  setSelected(null)
                }}
              />
            </div>
          )}
        </Group>
      )}
      <ChangesDrawer
        opened={changesOpen}
        onClose={() => {
          setChangesOpen(false)
        }}
      />
    </Stack>
  )
}
