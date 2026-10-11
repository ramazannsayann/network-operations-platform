import { MantineProvider } from '@mantine/core'
import { render } from '@testing-library/react'
import type { ReactElement } from 'react'

import { theme } from '../app/theme'

/** Render inside the providers the components need. */
export function renderWithProviders(ui: ReactElement) {
  return render(<MantineProvider theme={theme}>{ui}</MantineProvider>)
}
