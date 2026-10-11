import { Button } from '@mantine/core'
import { IconLock } from '@tabler/icons-react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'

import { EmptyState } from '../components/EmptyState'
import { type Permission, useMe } from './context'

export function ForbiddenPage({ permission }: { permission: Permission }) {
  const { t } = useTranslation()
  const me = useMe()
  return (
    <EmptyState
      icon={IconLock}
      title={t('auth.forbidden.title')}
      body={t('auth.forbidden.body', { role: t(`enums.userRole.${me.role}`), permission })}
      action={
        <Button component={Link} to="/" variant="light">
          {t('common.backHome')}
        </Button>
      }
    />
  )
}
