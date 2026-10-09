import { Tooltip } from '@mantine/core'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { dateTime, relativeTime } from '../lib/format'

/** "3 dk. önce", with the exact time on hover; re-renders every 30 s. */
export function RelativeTime({ value }: { value: string | null | undefined }) {
  const { t, i18n } = useTranslation()
  const [now, setNow] = useState(() => new Date())
  useEffect(() => {
    const timer = setInterval(() => {
      setNow(new Date())
    }, 30_000)
    return () => {
      clearInterval(timer)
    }
  }, [])
  if (!value) return <>{t('common.never')}</>
  const exact = dateTime(value, i18n.language)
  return (
    <Tooltip label={exact}>
      <time dateTime={value} aria-label={exact}>
        {relativeTime(value, i18n.language, now)}
      </time>
    </Tooltip>
  )
}
