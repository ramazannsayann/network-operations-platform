import { Alert, Button, List, PasswordInput, Stack, Text } from '@mantine/core'
import { IconCheck } from '@tabler/icons-react'
import { type FormEvent, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { useChangePassword } from '../../api/queries'
import { ProblemAlert } from '../../components/ProblemAlert'
import { fieldErrors, passwordMessageKey } from './problems'

const MIN_LENGTH = 12

/** Change the own password: current, new, repeated. Other sessions end on success. */
export function PasswordForm({ onDone }: { onDone?: () => void }) {
  const { t } = useTranslation()
  const change = useChangePassword()
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [repeat, setRepeat] = useState('')
  const [mismatch, setMismatch] = useState(false)
  const errors = fieldErrors(change.error)

  const submit = (event: FormEvent) => {
    event.preventDefault()
    setMismatch(next !== repeat)
    if (next !== repeat) return
    change.mutate(
      { current_password: current, new_password: next },
      {
        onSuccess: () => {
          setCurrent('')
          setNext('')
          setRepeat('')
          onDone?.()
        },
      },
    )
  }
  const newErrors = errors.new_password ?? []
  const otherError = change.isError && !errors.new_password && !errors.current_password

  return (
    <form onSubmit={submit} noValidate>
      <Stack gap="sm" maw={420}>
        <PasswordInput
          label={t('account.password.current')}
          autoComplete="current-password"
          value={current}
          onChange={(event) => {
            setCurrent(event.currentTarget.value)
          }}
          error={errors.current_password ? t('account.password.errors.wrong') : undefined}
          required
        />
        <PasswordInput
          label={t('account.password.new')}
          description={t('account.password.policy', { min: MIN_LENGTH })}
          autoComplete="new-password"
          value={next}
          onChange={(event) => {
            setNext(event.currentTarget.value)
          }}
          error={
            newErrors.length > 0 ? (
              <List size="xs">
                {newErrors.map((type) => (
                  <List.Item key={type}>
                    {t(passwordMessageKey(type), { min: MIN_LENGTH })}
                  </List.Item>
                ))}
              </List>
            ) : undefined
          }
          required
        />
        <PasswordInput
          label={t('account.password.repeat')}
          autoComplete="new-password"
          value={repeat}
          onChange={(event) => {
            setRepeat(event.currentTarget.value)
          }}
          error={mismatch ? t('account.password.mismatch') : undefined}
          required
        />
        {otherError && <ProblemAlert error={change.error} />}
        {change.isSuccess && (
          <Alert color="teal" variant="light" icon={<IconCheck size={16} />}>
            {t('account.password.changed')}
          </Alert>
        )}
        <Text size="xs" c="dimmed">
          {t('account.password.otherSessions')}
        </Text>
        <Button type="submit" loading={change.isPending} disabled={!current || !next || !repeat}>
          {t('account.password.submit')}
        </Button>
      </Stack>
    </form>
  )
}
