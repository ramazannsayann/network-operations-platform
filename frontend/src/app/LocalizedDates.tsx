import 'dayjs/locale/tr'

import { DatesProvider } from '@mantine/dates'
import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'

/** Date pickers follow the UI language (month names, first day of the week). */
export function LocalizedDates({ children }: { children: ReactNode }) {
  const { i18n } = useTranslation()
  return (
    <DatesProvider settings={{ locale: i18n.language, firstDayOfWeek: 1 }}>
      {children}
    </DatesProvider>
  )
}
