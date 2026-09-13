import { BrowserRouter, Route, Routes } from 'react-router-dom'
import { MantineProvider } from '@mantine/core'
import { Notifications } from '@mantine/notifications'
import { AuthProvider } from './auth/AuthContext'
import RequireAuth from './auth/RequireAuth'
import LandingPage from './pages/LandingPage'
import AuthPage from './pages/AuthPage'
import DashboardLayout from './pages/dashboard/DashboardLayout'
import AppointmentsPage from './pages/dashboard/AppointmentsPage'
import ServicesPage from './pages/dashboard/ServicesPage'
import StaffPage from './pages/dashboard/StaffPage'
import HoursPage from './pages/dashboard/HoursPage'
import KnowledgePage from './pages/dashboard/KnowledgePage'
import TrainingRoomPage from './pages/dashboard/TrainingRoomPage'
import HandoffsPage from './pages/dashboard/HandoffsPage'
import FollowUpsPage from './pages/dashboard/FollowUpsPage'
import OverviewPage from './pages/dashboard/OverviewPage'
import ReportsPage from './pages/dashboard/ReportsPage'
import WebsiteWidgetPage from './pages/dashboard/WebsiteWidgetPage'
import GoogleCalendarPage from './pages/dashboard/GoogleCalendarPage'
import ChannelsPage from './pages/dashboard/ChannelsPage'
import PaymentsPage from './pages/dashboard/PaymentsPage'
import SettingsPage from './pages/dashboard/SettingsPage'

import '@mantine/core/styles.css'
import '@mantine/notifications/styles.css'
import '@mantine/charts/styles.css'

export default function App() {
  return (
    <MantineProvider defaultColorScheme="light">
      <Notifications />
      <BrowserRouter>
        <AuthProvider>
          <Routes>
            <Route path="/" element={<LandingPage />} />
            <Route path="/login" element={<AuthPage />} />
            <Route path="/register" element={<AuthPage />} />

            <Route element={<RequireAuth />}>
              <Route path="/dashboard" element={<DashboardLayout />}>
                <Route index element={<OverviewPage />} />
                <Route path="appointments" element={<AppointmentsPage />} />
                <Route path="services" element={<ServicesPage />} />
                <Route path="staff" element={<StaffPage />} />
                <Route path="hours" element={<HoursPage />} />
                <Route path="knowledge" element={<KnowledgePage />} />
                <Route path="training" element={<TrainingRoomPage />} />
                <Route path="handoffs" element={<HandoffsPage />} />
                <Route path="reports" element={<ReportsPage />} />
                <Route path="followups" element={<FollowUpsPage />} />
                <Route path="widget" element={<WebsiteWidgetPage />} />
                <Route path="google-calendar" element={<GoogleCalendarPage />} />
                <Route path="channels" element={<ChannelsPage />} />
                <Route path="payments" element={<PaymentsPage />} />
                <Route path="settings" element={<SettingsPage />} />
              </Route>
            </Route>
          </Routes>
        </AuthProvider>
      </BrowserRouter>
    </MantineProvider>
  )
}
