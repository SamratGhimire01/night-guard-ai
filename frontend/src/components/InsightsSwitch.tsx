import { useLocation, useNavigate } from 'react-router-dom'
import { SegmentedControl } from '@mantine/core'
import { useAuth } from '../auth/AuthContext'

/** Reports and Analytics are one "Insights" area in the menu; this switches between the two. */
export default function InsightsSwitch() {
  const { role } = useAuth()
  const { pathname } = useLocation()
  const navigate = useNavigate()
  if (role !== 'owner' && role !== 'admin') return null // analytics is owners/admins only: nothing to switch to
  return (
    <SegmentedControl
      aria-label="Insights"
      value={pathname.startsWith('/dashboard/analytics') ? 'analytics' : 'reports'}
      onChange={(v) => navigate(v === 'analytics' ? '/dashboard/analytics' : '/dashboard/reports')}
      data={[
        { value: 'reports', label: 'Reports' },
        { value: 'analytics', label: 'Trends' },
      ]}
      style={{ alignSelf: 'flex-start' }}
    />
  )
}
