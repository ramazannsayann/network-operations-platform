import {
  Alert,
  Anchor,
  Button,
  Card,
  Code,
  Grid,
  Group,
  MultiSelect,
  ScrollArea,
  Skeleton,
  Stack,
  Table,
  TagsInput,
  Text,
  Title,
  VisuallyHidden,
} from '@mantine/core'
import { IconPlayerPlay, IconRadar } from '@tabler/icons-react'
import { type FormEvent, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useNavigate } from 'react-router'

import { useCredentialProfiles, useDiscoveryRuns, useStartDiscovery } from '../../api/queries'
import { EmptyState } from '../../components/EmptyState'
import { ProblemAlert } from '../../components/ProblemAlert'
import { RelativeTime } from '../../components/RelativeTime'
import { JobStatusBadge } from '../../components/StatusBadges'
import { type DiscoveryFormErrors, normalizeTags, validateDiscoveryForm } from '../../lib/ip'

const SPLIT = [',', ' ', ';', '\n']

export function DiscoveryForm() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const profiles = useCredentialProfiles()
  const start = useStartDiscovery()
  const [seeds, setSeeds] = useState<string[]>([])
  const [subnets, setSubnets] = useState<string[]>([])
  const [profileIds, setProfileIds] = useState<string[]>([])
  const [errors, setErrors] = useState<DiscoveryFormErrors>({})
  const [submitted, setSubmitted] = useState(false)

  const values = { seeds, allowedSubnets: subnets, credentialProfileIds: profileIds }
  const revalidate = (next: typeof values) => {
    if (submitted) setErrors(validateDiscoveryForm(next))
  }

  const onSubmit = (event: FormEvent) => {
    event.preventDefault()
    setSubmitted(true)
    const found = validateDiscoveryForm(values)
    setErrors(found)
    if (Object.keys(found).length > 0) return
    start.mutate(
      { seeds, allowed_subnets: subnets, credential_profile_ids: profileIds },
      {
        onSuccess: (job) => {
          void navigate(job.target_href.replace('/api/v1', ''))
        },
      },
    )
  }

  const noProfiles = profiles.data?.total === 0
  return (
    <Card withBorder component="form" onSubmit={onSubmit} noValidate>
      <Title order={3} size="h4" mb="sm">
        {t('discovery.form.title')}
      </Title>
      <Stack gap="sm">
        <TagsInput
          label={t('discovery.form.seeds')}
          description={t('discovery.form.seedsHelp')}
          placeholder="10.0.0.1"
          splitChars={SPLIT}
          value={seeds}
          onChange={(value) => {
            const tags = normalizeTags(value)
            setSeeds(tags)
            revalidate({ ...values, seeds: tags })
          }}
          error={errors.seeds ? t(errors.seeds) : undefined}
          required
          clearable
        />
        <TagsInput
          label={t('discovery.form.subnets')}
          description={t('discovery.form.subnetsHelp')}
          placeholder="10.0.0.0/16"
          splitChars={SPLIT}
          value={subnets}
          onChange={(value) => {
            const tags = normalizeTags(value)
            setSubnets(tags)
            revalidate({ ...values, allowedSubnets: tags })
          }}
          error={errors.allowedSubnets ? t(errors.allowedSubnets) : undefined}
          required
          clearable
        />
        <MultiSelect
          label={t('discovery.form.profiles')}
          description={t('discovery.form.profilesHelp')}
          data={(profiles.data?.items ?? []).map((profile) => ({
            value: profile.id,
            label: profile.name,
          }))}
          value={profileIds}
          onChange={(value) => {
            setProfileIds(value)
            revalidate({ ...values, credentialProfileIds: value })
          }}
          error={errors.credentialProfileIds ? t(errors.credentialProfileIds) : undefined}
          disabled={profiles.isPending}
          required
          searchable
        />
        {noProfiles && (
          <Alert color="yellow" variant="light">
            {t('discovery.form.noProfiles')}
          </Alert>
        )}
        {profiles.isError && <ProblemAlert error={profiles.error} />}
        {start.isError && <ProblemAlert error={start.error} />}
        <Group justify="flex-end">
          <Button
            type="submit"
            leftSection={<IconPlayerPlay size={16} aria-hidden />}
            loading={start.isPending}
          >
            {t('discovery.form.submit')}
          </Button>
        </Group>
      </Stack>
    </Card>
  )
}

function RunList() {
  const { t } = useTranslation()
  const runs = useDiscoveryRuns()
  return (
    <Card withBorder>
      <Title order={3} size="h4" mb="sm">
        {t('discovery.runs.title')}
      </Title>
      {runs.isError && <ProblemAlert error={runs.error} onRetry={() => void runs.refetch()} />}
      {runs.isPending && <Skeleton height={120} />}
      {runs.data?.total === 0 && <EmptyState icon={IconRadar} title={t('discovery.runs.empty')} />}
      {runs.data && runs.data.total > 0 && (
        <ScrollArea>
          <Table highlightOnHover verticalSpacing="xs" miw={560}>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>{t('discovery.runs.requested')}</Table.Th>
                <Table.Th>{t('discovery.runs.status')}</Table.Th>
                <Table.Th>{t('discovery.runs.found')}</Table.Th>
                <Table.Th>{t('discovery.runs.skipped')}</Table.Th>
                <Table.Th>{t('discovery.runs.errors')}</Table.Th>
                <Table.Th>
                  <VisuallyHidden>{t('discovery.runs.open')}</VisuallyHidden>
                </Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {runs.data.items.map((run) => (
                <Table.Tr key={run.id}>
                  <Table.Td>
                    <RelativeTime value={run.requested_at} />
                  </Table.Td>
                  <Table.Td>
                    <JobStatusBadge status={run.status} />
                  </Table.Td>
                  <Table.Td>{run.progress.found}</Table.Td>
                  <Table.Td>{run.progress.skipped}</Table.Td>
                  <Table.Td>{run.progress.errors}</Table.Td>
                  <Table.Td>
                    <Anchor component={Link} to={`/discovery/runs/${run.id}`}>
                      {t('discovery.runs.open')}
                    </Anchor>
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </ScrollArea>
      )}
      <Text size="xs" c="dimmed" mt="sm">
        CLI: <Code>netops discover --seed … --subnet … --profile …</Code>
      </Text>
    </Card>
  )
}

export function DiscoveryPage() {
  const { t } = useTranslation()
  return (
    <Stack gap="md">
      <Title order={2}>{t('discovery.title')}</Title>
      <Grid>
        <Grid.Col span={{ base: 12, lg: 5 }}>
          <DiscoveryForm />
        </Grid.Col>
        <Grid.Col span={{ base: 12, lg: 7 }}>
          <RunList />
        </Grid.Col>
      </Grid>
    </Stack>
  )
}
