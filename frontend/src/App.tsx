import { Center, Loader } from '@mantine/core'
import { lazy, Suspense, type ReactNode } from 'react'
import { Navigate, Route, Routes, useLocation } from 'react-router-dom'

import { useAuth } from './auth/AuthContext'
import { BASE, loginHref } from './contour'
import { AppLayout } from './layout/AppLayout'
import { AdministrationPage } from './pages/AdministrationPage'
import { AnalyticsPage } from './pages/AnalyticsPage'
import { DashboardPage } from './pages/DashboardPage'
import { DataHealthPage } from './pages/DataHealthPage'
import { DataImportPage } from './pages/DataImportPage'
import { DataQualityPage } from './pages/DataQualityPage'
import { EquipmentPage } from './pages/EquipmentPage'
import { ExerciseDetailPage } from './pages/ExerciseDetailPage'
import { ExercisesPage } from './pages/ExercisesPage'
import { ForecastCardPage } from './pages/ForecastCardPage'
import { ForecastsPage } from './pages/ForecastsPage'
import { HistoryPage } from './pages/HistoryPage'
import { IncidentDetailPage } from './pages/IncidentDetailPage'
import { IncidentsPage } from './pages/IncidentsPage'
import { IntegrationsPage } from './pages/IntegrationsPage'
import { LearningPage } from './pages/LearningPage'
import { LoginPage } from './pages/LoginPage'
import { MaintenancePage } from './pages/MaintenancePage'
import { ModelsPage } from './pages/ModelsPage'
import { MonitoringPage } from './pages/MonitoringPage'
import { ReplayPage } from './pages/ReplayPage'
import { SchedulesPage } from './pages/SchedulesPage'
import { SchemePage } from './pages/SchemePage'

// редактор структуры тянет картографический движок — отдельный чанк
const StructurePage = lazy(() => import('./pages/StructurePage').then((m) => ({ default: m.StructurePage })))
import { TeamsPage } from './pages/TeamsPage'
import { TrainingPage } from './pages/TrainingPage'
import { WorkOrdersPage } from './pages/WorkOrdersPage'
import { WikiPage } from './pages/WikiPage'
import { WorkspacePage } from './pages/WorkspacePage'

function RequireAuth({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth()
  const location = useLocation()
  if (loading) {
    return (
      <Center mih="100vh">
        <Loader />
      </Center>
    )
  }
  if (user) return children
  // вход один на платформу — в основной системе; из учебного контура уходим туда с возвратом
  if (BASE) {
    window.location.replace(loginHref())
    return null
  }
  return <Navigate to={loginHref(location.pathname + location.search)} replace />
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
        <Route index element={<MonitoringPage />} />
        <Route path="workspace" element={<WorkspacePage />} />
        <Route path="overview" element={<DashboardPage />} />
        <Route path="incidents" element={<IncidentsPage />} />
        <Route path="incidents/:id" element={<IncidentDetailPage />} />
        <Route path="map" element={<SchemePage />} />
        <Route path="forecasts" element={<ForecastsPage />} />
        <Route path="forecasts/:id" element={<ForecastCardPage />} />
        <Route path="models" element={<ModelsPage />} />
        <Route path="learning" element={<LearningPage />} />
        <Route path="data-health" element={<DataHealthPage />} />
        <Route path="workorders" element={<WorkOrdersPage />} />
        <Route path="maintenance" element={<MaintenancePage />} />
        <Route path="equipment" element={<EquipmentPage />} />
        <Route path="schedules" element={<SchedulesPage />} />
        <Route path="integrations" element={<IntegrationsPage />} />
        <Route path="replay" element={<ReplayPage />} />
        <Route path="history" element={<HistoryPage />} />
        <Route path="analytics" element={<AnalyticsPage />} />
        <Route path="teams" element={<TeamsPage />} />
        <Route path="training" element={<TrainingPage />} />
        <Route path="exercises" element={<ExercisesPage />} />
        <Route path="exercises/:id" element={<ExerciseDetailPage />} />
        <Route
          path="structure"
          element={
            <Suspense fallback={<Loader />}>
              <StructurePage />
            </Suspense>
          }
        />
        <Route path="administration" element={<AdministrationPage />} />
        <Route path="wiki" element={<WikiPage />} />
        <Route path="wiki/:slug" element={<WikiPage />} />
        <Route path="data-import" element={<DataImportPage />} />
        <Route path="data-quality" element={<DataQualityPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  )
}
