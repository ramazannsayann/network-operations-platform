import { Alert, Button, Checkbox, CopyButton, Group, SimpleGrid, Stack, Text } from '@mantine/core'
import { IconAlertTriangle, IconCopy, IconDownload } from '@tabler/icons-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

/** The recovery codes, shown once: the platform keeps only their hashes. */
export function RecoveryCodes({ codes, onDone }: { codes: string[]; onDone: () => void }) {
  const { t } = useTranslation()
  const [saved, setSaved] = useState(false)
  const text = codes.join('\n') + '\n'
  return (
    <Stack gap="sm">
      <Alert color="yellow" variant="light" icon={<IconAlertTriangle size={18} />}>
        {t('account.mfa.codesOnce')}
      </Alert>
      <SimpleGrid cols={2} spacing="xs" data-testid="recovery-codes">
        {codes.map((code) => (
          <Text key={code} className="mono" fw={600}>
            {code}
          </Text>
        ))}
      </SimpleGrid>
      <Group gap="xs">
        <CopyButton value={text}>
          {({ copied, copy }) => (
            <Button variant="default" size="xs" leftSection={<IconCopy size={14} />} onClick={copy}>
              {copied ? t('account.mfa.copied') : t('account.mfa.copy')}
            </Button>
          )}
        </CopyButton>
        <Button
          variant="default"
          size="xs"
          leftSection={<IconDownload size={14} />}
          component="a"
          href={`data:text/plain;charset=utf-8,${encodeURIComponent(text)}`}
          download="netops-recovery-codes.txt"
        >
          {t('account.mfa.download')}
        </Button>
      </Group>
      <Checkbox
        label={t('account.mfa.saved')}
        checked={saved}
        onChange={(event) => {
          setSaved(event.currentTarget.checked)
        }}
      />
      <Button onClick={onDone} disabled={!saved}>
        {t('account.mfa.finish')}
      </Button>
    </Stack>
  )
}
