import { BrowserRouter, Route, Routes } from 'react-router-dom'
import { MantineProvider } from '@mantine/core'
import { Notifications } from '@mantine/notifications'
import { AuthProvider } from './auth/AuthContext'
import RequireAuth from './auth/RequireAuth'
import LandingPage from './pages/LandingPage'
import AuthPage from './pages/AuthPage'
import DashboardLayout from './pages/dashboard/DashboardLayout'
import PlaceholderPage from './pages/dashboard/PlaceholderPage'

import '@mantine/core/styles.css'
import '@mantine/notifications/styles.css'

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
                <Route index element={<PlaceholderPage title="Overview" />} />
                <Route path="appointments" element={<PlaceholderPage title="Appointments" />} />
                <Route path="services" element={<PlaceholderPage title="Services" />} />
                <Route path="staff" element={<PlaceholderPage title="Staff" />} />
                <Route path="hours" element={<PlaceholderPage title="Business Hours" />} />
                <Route path="knowledge" element={<PlaceholderPage title="Knowledge Base" />} />
                <Route path="training" element={<PlaceholderPage title="AI Training Room" />} />
                <Route path="handoffs" element={<PlaceholderPage title="Human Handoffs" />} />
                <Route path="reports" element={<PlaceholderPage title="Reports" />} />
                <Route path="followups" element={<PlaceholderPage title="Follow-ups" />} />
                <Route path="settings" element={<PlaceholderPage title="Settings" />} />
              </Route>
            </Route>
          </Routes>
        </AuthProvider>
      </BrowserRouter>
    </MantineProvider>
  )
}
