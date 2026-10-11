import { Anchor, Button, Code, Group, ScrollArea, Stack, Table, Text } from '@mantine/core'
import { IconArrowsDiff } from '@tabler/icons-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'

import type { Schemas } from '../../api/client'
import { RelativeTime } from '../../components/RelativeTime'
import { OriginBadge } from './badges'
import { diffLink } from './links'

type Change = Schemas['ConfigChange']

const SHOWN_COMMANDS = 3

function Commands({ commands }: { commands: string[] }) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  if (commands.length === 0) return <Text c="dimmed">{t('common.none')}</Text>
  const shown = open ? commands : commands.slice(0, SHOWN_COMMANDS)
  return (
    <Stack gap={2}>
      <Code block>{shown.join('\n')}</Code>
      {commands.length > SHOWN_COMMANDS && (
        <Anchor
          component="button"
          size="xs"
          onClick={() => {
            setOpen(!open)
          }}
        >
          {open
            ? t('configs.changes.fewer')
            : t('configs.changes.more', { count: commands.length - SHOWN_COMMANDS })}
        </Anchor>
      )}
    </Stack>
  )
}

function Who({ change }: { change: Change }) {
  const { t } = useTranslation()
  if (change.username) return <Text fw={500}>{change.username}</Text>
  return (
    <Stack gap={0}>
      <Text c="dimmed">{t('common.unknown')}</Text>
      {change.detected_by && change.detected_by !== 'change_event' && (
        <Text size="xs" c="dimmed">
          {t(`configs.changes.foundBy.${change.detected_by}`)}
        </Text>
      )}
    </Stack>
  )
}

/** Detected changes: who, from where, which commands, and the diff of the two versions. */
export function ChangesTable({ items, showDevice }: { items: Change[]; showDevice: boolean }) {
  const { t } = useTranslation()
  return (
    <ScrollArea>
      <Table verticalSpacing="xs" miw={showDevice ? 1040 : 880} data-testid="config-changes">
        <Table.Thead>
          <Table.Tr>
            <Table.Th>{t('configs.changes.when')}</Table.Th>
            {showDevice && <Table.Th>{t('configs.changes.device')}</Table.Th>}
            <Table.Th>{t('configs.changes.origin')}</Table.Th>
            <Table.Th>{t('configs.changes.user')}</Table.Th>
            <Table.Th>{t('configs.changes.sourceIp')}</Table.Th>
            <Table.Th>{t('configs.changes.commands')}</Table.Th>
            <Table.Th>{t('configs.changes.diff')}</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {items.map((change) => {
            const link = diffLink(change)
            return (
              <Table.Tr key={change.id}>
                <Table.Td>
                  <RelativeTime value={change.detected_at} />
                </Table.Td>
                {showDevice && (
                  <Table.Td>
                    <Anchor
                      component={Link}
                      to={`/devices/${change.device.id}?tab=config`}
                      fw={500}
                    >
                      {change.device.hostname ?? change.device.mgmt_ip}
                    </Anchor>
                  </Table.Td>
                )}
                <Table.Td>
                  <Group gap={4}>
                    <OriginBadge origin={change.origin} />
                  </Group>
                </Table.Td>
                <Table.Td>
                  <Who change={change} />
                </Table.Td>
                <Table.Td className="mono">{change.source_ip ?? t('common.none')}</Table.Td>
                <Table.Td maw={420}>
                  <Commands commands={change.commands} />
                </Table.Td>
                <Table.Td>
                  {link ? (
                    <Button
                      component={Link}
                      to={link}
                      size="xs"
                      variant="light"
                      leftSection={<IconArrowsDiff size={14} aria-hidden />}
                    >
                      {t('configs.changes.showDiff')}
                    </Button>
                  ) : (
                    t('common.none')
                  )}
                </Table.Td>
              </Table.Tr>
            )
          })}
        </Table.Tbody>
      </Table>
    </ScrollArea>
  )
}
