import { Center, Loader } from '@mantine/core'
import type { ReactNode } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'

import { useAuth } from './auth/AuthContext'
import { AppLayout } from './layout/AppLayout'
import { AnalyticsPage } from './pages/AnalyticsPage'
import { DashboardPage } from './pages/DashboardPage'
import { DataHealthPage } from './pages/DataHealthPage'
import { DataImportPage } from './pages/DataImportPage'
import { DataQualityPage } from './pages/DataQualityPage'
import { ExerciseDetailPage } from './pages/ExerciseDetailPage'
import { ExercisesPage } from './pages/ExercisesPage'
import { ForecastCardPage } from './pages/ForecastCardPage'
import { ForecastsPage } from './pages/ForecastsPage'
import { HistoryPage } from './pages/HistoryPage'
import { IncidentDetailPage } from './pages/IncidentDetailPage'
import { IncidentsPage } from './pages/IncidentsPage'
import { LearningPage } from './pages/LearningPage'
import { LoginPage } from './pages/LoginPage'
import { ModelsPage } from './pages/ModelsPage'
import { ReplayPage } from './pages/ReplayPage'
import { SchemePage } from './pages/SchemePage'
import { TeamsPage } from './pages/TeamsPage'
import { TrainingPage } from './pages/TrainingPage'
import { WorkOrdersPage } from './pages/WorkOrdersPage'
import { WikiPage } from './pages/WikiPage'
import { WorkspacePage } from './pages/WorkspacePage'

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
        <Route index element={<WorkspacePage />} />
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
        <Route path="replay" element={<ReplayPage />} />
        <Route path="history" element={<HistoryPage />} />
        <Route path="analytics" element={<AnalyticsPage />} />
        <Route path="teams" element={<TeamsPage />} />
        <Route path="training" element={<TrainingPage />} />
        <Route path="exercises" element={<ExercisesPage />} />
        <Route path="exercises/:id" element={<ExerciseDetailPage />} />
        <Route path="wiki" element={<WikiPage />} />
        <Route path="wiki/:slug" element={<WikiPage />} />
        <Route path="data-import" element={<DataImportPage />} />
        <Route path="data-quality" element={<DataQualityPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  )
}
