import { Center, Loader } from '@mantine/core'
import type { ReactNode } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'

import { useAuth } from './auth/AuthContext'
import { AppLayout } from './layout/AppLayout'
import { DashboardPage } from './pages/DashboardPage'
import { DataHealthPage } from './pages/DataHealthPage'
import { DataImportPage } from './pages/DataImportPage'
import { DataQualityPage } from './pages/DataQualityPage'
import { ForecastsPage } from './pages/ForecastsPage'
import { IncidentDetailPage } from './pages/IncidentDetailPage'
import { IncidentsPage } from './pages/IncidentsPage'
import { LoginPage } from './pages/LoginPage'
import { ModelsPage } from './pages/ModelsPage'
import { PlannedPage } from './pages/PlannedPage'
import { TeamsPage } from './pages/TeamsPage'

function RequireAuth({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth()
  if (loading) {
    return (
      <Center mih="100vh">
        <Loader />
      </Center>
    )
  }
  return user ? children : <Navigate to="/login" replace />
}

export function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        element={
          <RequireAuth>
            <AppLayout />
          </RequireAuth>
        }
      >
        <Route index element={<DashboardPage />} />
        <Route path="incidents" element={<IncidentsPage />} />
        <Route path="incidents/:id" element={<IncidentDetailPage />} />
        <Route
          path="map"
          element={
            <PlannedPage
              title="Схема объектов"
              epic="E5"
              description="Линейная схема коллекторов по пикетам с цветовой индикацией риска (GeoJSON, масштабирование)."
            />
          }
        />
        <Route path="forecasts" element={<ForecastsPage />} />
        <Route path="models" element={<ModelsPage />} />
        <Route path="data-health" element={<DataHealthPage />} />
        <Route
          path="workorders"
          element={
            <PlannedPage
              title="Заявки"
              epic="E4/E7"
              description="Черновики и заявки на работы, утверждение, статусы из системы учёта заявок."
            />
          }
        />
        <Route
          path="analytics"
          element={
            <PlannedPage
              title="Аналитика"
              epic="E6"
              description="Статистика по типам инцидентов, сезонность, качество прогнозов, отчёты PDF/XLSX."
            />
          }
        />
        <Route path="teams" element={<TeamsPage />} />
        <Route path="data-import" element={<DataImportPage />} />
        <Route path="data-quality" element={<DataQualityPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  )
}
