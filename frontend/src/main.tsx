import '@mantine/core/styles.css'
import '@mantine/charts/styles.css'
import '@mantine/dates/styles.css'
import '@mantine/notifications/styles.css'
import './training/tour.css'

import { MantineProvider, createTheme } from '@mantine/core'
import { Notifications } from '@mantine/notifications'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import dayjs from 'dayjs'
import 'dayjs/locale/ru'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'

import { App } from './App'
import { AuthProvider } from './auth/AuthContext'
import { BASE } from './contour'

dayjs.locale('ru')

const theme = createTheme({
  primaryColor: 'blue',
  defaultRadius: 'md',
  fontFamily: 'Inter, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif',
})

const queryClient = new QueryClient({
  defaultOptions: { queries: { refetchOnWindowFocus: true, staleTime: 10_000 } },
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <MantineProvider theme={theme} defaultColorScheme="auto">
      <Notifications position="top-right" limit={5} />
      <QueryClientProvider client={queryClient}>
        {/* учебный контур — подсистема под /training/: тот же интерфейс со своим префиксом маршрутов */}
        <BrowserRouter basename={BASE || undefined}>
          <AuthProvider>
            <App />
          </AuthProvider>
        </BrowserRouter>
      </QueryClientProvider>
    </MantineProvider>
  </StrictMode>,
)
