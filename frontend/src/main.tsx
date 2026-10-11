import '@mantine/core/styles.css'
import '@mantine/dates/styles.css'
import './index.css'
import './i18n'

import { MantineProvider } from '@mantine/core'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { RouterProvider } from 'react-router'

import { LocalizedDates } from './app/LocalizedDates'
import { router } from './app/router'
import { theme } from './app/theme'
import { AuthProvider } from './auth/AuthProvider'

const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 10_000, retry: 1, refetchOnWindowFocus: false } },
})

const container = document.getElementById('root')
if (!container) throw new Error('index.html is missing the #root element')

createRoot(container).render(
  <StrictMode>
    <MantineProvider theme={theme} defaultColorScheme="auto">
      <LocalizedDates>
        <QueryClientProvider client={queryClient}>
          <AuthProvider>
            <RouterProvider router={router} />
          </AuthProvider>
        </QueryClientProvider>
      </LocalizedDates>
    </MantineProvider>
  </StrictMode>,
)
