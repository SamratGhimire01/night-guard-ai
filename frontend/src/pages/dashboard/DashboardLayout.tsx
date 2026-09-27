import { useEffect, useState, type ReactNode } from 'react'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import {
  ActionIcon,
  AppShell,
  Badge,
  Burger,
  Group,
  NavLink as MantineNavLink,
  ScrollArea,
  Skeleton,
  Text,
  ThemeIcon,
  Tooltip,
  useComputedColorScheme,
  useMantineColorScheme,
} from '@mantine/core'
import { useDisclosure } from '@mantine/hooks'
import {
  IconBook2,
  IconCalendarEvent,
  IconCalendarRepeat,
  IconChartBar,
  IconChartLine,
  IconClock,
  IconCreditCard,
  IconDental,
  IconHeadset,
  IconInbox,
  IconLayoutDashboard,
  IconLogout,
  IconMessageCircle,
  IconMoon,
  IconMoonStars,
  IconPlugConnected,
  IconQrcode,
  IconRepeat,
  IconSettings,
  IconSparkles,
  IconSun,
  IconUsers,
} from '@tabler/icons-react'
import { useAuth } from '../../auth/AuthContext'
import { apiFetch } from '../../api/client'
import type { BusinessRead, InboxSummary, PlanRead } from '../../api/types'
import { usePolling } from './inbox/usePolling'
import StatusBadge from '../../components/StatusBadge'

const ICON = { size: 18, stroke: 1.75 }

const NAV_SECTIONS: { label: string; to: string; icon: ReactNode; ownerAdminOnly?: boolean }[] = [
  { label: 'Overview', to: '/dashboard', icon: <IconLayoutDashboard {...ICON} /> },
  { label: 'Inbox', to: '/dashboard/inbox', icon: <IconInbox {...ICON} /> },
  { label: 'Appointments', to: '/dashboard/appointments', icon: <IconCalendarEvent {...ICON} /> },
  { label: 'Services', to: '/dashboard/services', icon: <IconDental {...ICON} /> },
  { label: 'Staff', to: '/dashboard/staff', icon: <IconUsers {...ICON} /> },
  { label: 'Business Hours', to: '/dashboard/hours', icon: <IconClock {...ICON} /> },
  { label: 'Knowledge Base', to: '/dashboard/knowledge', icon: <IconBook2 {...ICON} /> },
  { label: 'AI Training Room', to: '/dashboard/training', icon: <IconSparkles {...ICON} /> },
  { label: 'Human Handoffs', to: '/dashboard/handoffs', icon: <IconHeadset {...ICON} /> },
  { label: 'Reports', to: '/dashboard/reports', icon: <IconChartBar {...ICON} /> },
  { label: 'Analytics', to: '/dashboard/analytics', icon: <IconChartLine {...ICON} />, ownerAdminOnly: true },
  { label: 'Follow-ups', to: '/dashboard/followups', icon: <IconRepeat {...ICON} /> },
  { label: 'Website Widget', to: '/dashboard/widget', icon: <IconMessageCircle {...ICON} /> },
  { label: 'Google Calendar', to: '/dashboard/google-calendar', icon: <IconCalendarRepeat {...ICON} /> },
  { label: 'Channels', to: '/dashboard/channels', icon: <IconPlugConnected {...ICON} />, ownerAdminOnly: true },
  { label: 'Payments', to: '/dashboard/payments', icon: <IconCreditCard {...ICON} /> },
  { label: 'Check-in Scanner', to: '/dashboard/checkin', icon: <IconQrcode {...ICON} /> },
  { label: 'Settings', to: '/dashboard/settings', icon: <IconSettings {...ICON} /> },
]

function ThemeToggle() {
  const { setColorScheme } = useMantineColorScheme()
  const computed = useComputedColorScheme('dark')
  const isDark = computed === 'dark'
  return (
    <Tooltip label={isDark ? 'Switch to light mode' : 'Switch to dark mode'}>
      <ActionIcon
        size="lg"
        aria-label="Toggle color scheme"
        onClick={() => setColorScheme(isDark ? 'light' : 'dark')}
      >
        {isDark ? <IconSun {...ICON} /> : <IconMoon {...ICON} />}
      </ActionIcon>
    </Tooltip>
  )
}

export default function DashboardLayout() {
  const [opened, { toggle, close }] = useDisclosure()
  const { logout, role } = useAuth()
  const canAccessOwnerAdminOnly = role === 'owner' || role === 'admin'
  const navigate = useNavigate()
  const { pathname } = useLocation()
  const [business, setBusiness] = useState<BusinessRead | null>(null)
  const [plan, setPlan] = useState<PlanRead | null>(null)
  const [waiting, setWaiting] = useState(0)

  // Sidebar badge: conversations waiting for a person. Quiet on failure (the badge just doesn't update).
  usePolling(async () => {
    try {
      setWaiting((await apiFetch<InboxSummary>('/inbox/summary')).needs_reply)
    } catch {
      /* keep the last known count */
    }
  }, 30000)

  useEffect(() => {
    let cancelled = false
    Promise.all([apiFetch<BusinessRead>('/business/me'), apiFetch<PlanRead>('/business/plan')])
      .then(([b, p]) => {
        if (!cancelled) {
          setBusiness(b)
          setPlan(p)
        }
      })
      .catch(() => {
        /* a 401 here is already handled globally (redirect to /login); any
           other failure just leaves the header placeholders visible */
      })
    return () => {
      cancelled = true
    }
  }, [])

  function handleLogout() {
    logout()
    navigate('/login')
  }

  return (
    <AppShell
      header={{ height: 60 }}
      navbar={{ width: 250, breakpoint: 'sm', collapsed: { mobile: !opened } }}
      padding="lg"
    >
      <AppShell.Header>
        <Group h="100%" px="md" justify="space-between" wrap="nowrap">
          <Group gap="sm" wrap="nowrap">
            <Burger opened={opened} onClick={toggle} hiddenFrom="sm" size="sm" aria-label="Toggle navigation" />
            <ThemeIcon size={32} radius="md" variant="gradient" gradient={{ from: 'brand.5', to: 'violet.5', deg: 135 }}>
              <IconMoonStars size={19} stroke={1.75} />
            </ThemeIcon>
            <Text fw={700} fz="md">
              Night Guard AI
            </Text>
          </Group>
          <Group gap="sm" wrap="nowrap">
            {business ? (
              <Text fw={600} size="sm" visibleFrom="sm" truncate maw={220}>
                {business.name}
              </Text>
            ) : (
              <Skeleton height={16} width={140} visibleFrom="sm" />
            )}
            {plan ? <StatusBadge status={plan.plan} /> : <Skeleton height={20} width={60} radius="xl" />}
            <ThemeToggle />
            <Tooltip label="Log out">
              <ActionIcon size="lg" color="red" aria-label="Log out" onClick={handleLogout}>
                <IconLogout {...ICON} />
              </ActionIcon>
            </Tooltip>
          </Group>
        </Group>
      </AppShell.Header>

      <AppShell.Navbar p="md">
        <AppShell.Section grow component={ScrollArea} type="auto" scrollbarSize={6}>
          {NAV_SECTIONS.filter((item) => !item.ownerAdminOnly || canAccessOwnerAdminOnly).map((item) => (
            <MantineNavLink
              key={item.to}
              className="nav-item"
              component={NavLink}
              to={item.to}
              end={item.to === '/dashboard'}
              active={item.to === '/dashboard' ? pathname === item.to : pathname.startsWith(item.to)}
              label={item.label}
              leftSection={item.icon}
              rightSection={item.to === '/dashboard/inbox' && waiting > 0 ? <Badge color="orange" size="sm" circle>{waiting}</Badge> : undefined}
              onClick={close}
              mb={2}
            />
          ))}
        </AppShell.Section>
      </AppShell.Navbar>

      <AppShell.Main>
        <div style={{ maxWidth: 1280, margin: '0 auto' }}>
          <Outlet context={{ business, plan }} />
        </div>
      </AppShell.Main>
    </AppShell>
  )
}
