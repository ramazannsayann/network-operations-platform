import { Button, Code, Group, Image, PinInput, Stack, Stepper, Text } from '@mantine/core'
import { IconShieldLock } from '@tabler/icons-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { useBeginMfa, useConfirmMfa } from '../../api/queries'
import { ProblemAlert } from '../../components/ProblemAlert'
import { RecoveryCodes } from './RecoveryCodes'

/** TOTP enrollment: a secret (QR code or text) -> a first code -> the recovery codes. */
export function MfaEnrollment({ onDone }: { onDone: () => void }) {
  const { t } = useTranslation()
  const begin = useBeginMfa()
  const confirm = useConfirmMfa()
  const [code, setCode] = useState('')
  const step = confirm.data ? 2 : begin.data ? 1 : 0
  const secret = begin.data?.secret ?? ''

  return (
    <Stepper active={step} size="sm" allowNextStepsSelect={false}>
      <Stepper.Step label={t('account.mfa.step.start')}>
        <Stack gap="sm" mt="sm" maw={460}>
          <Text size="sm">{t('account.mfa.intro')}</Text>
          {begin.isError && <ProblemAlert error={begin.error} />}
          <Button
            leftSection={<IconShieldLock size={16} />}
            loading={begin.isPending}
            onClick={() => {
              begin.mutate()
            }}
          >
            {t('account.mfa.begin')}
          </Button>
        </Stack>
      </Stepper.Step>
      <Stepper.Step label={t('account.mfa.step.scan')}>
        <Stack gap="sm" mt="sm" maw={460}>
          <Text size="sm">{t('account.mfa.scan')}</Text>
          {begin.data && (
            <Image
              src={begin.data.qr_svg}
              alt={t('account.mfa.qrAlt')}
              w={220}
              h={220}
              bg="white"
              radius="sm"
            />
          )}
          <Text size="sm">{t('account.mfa.manual')}</Text>
          <Code data-testid="mfa-secret" style={{ wordBreak: 'break-all' }}>
            {secret.replace(/(.{4})/g, '$1 ').trim()}
          </Code>
          <Text size="sm" fw={500}>
            {t('account.mfa.enterCode')}
          </Text>
          <Group>
            <PinInput
              length={6}
              type="number"
              oneTimeCode
              value={code}
              onChange={setCode}
              ariaLabel={t('account.mfa.codeLabel')}
              getInputProps={(index) => ({
                'aria-label': `${t('account.mfa.codeLabel')} ${String(index + 1)}/6`,
              })}
            />
          </Group>
          {confirm.isError && <ProblemAlert error={confirm.error} />}
          <Button
            loading={confirm.isPending}
            disabled={code.length !== 6}
            onClick={() => {
              confirm.mutate(code)
            }}
          >
            {t('account.mfa.confirm')}
          </Button>
        </Stack>
      </Stepper.Step>
      <Stepper.Step label={t('account.mfa.step.codes')}>
        <Stack mt="sm" maw={460}>
          {confirm.data && <RecoveryCodes codes={confirm.data.recovery_codes} onDone={onDone} />}
        </Stack>
      </Stepper.Step>
    </Stepper>
  )
}
