import { useEffect, useState, type ComponentType } from 'react'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import {
  AppShell,
  Avatar,
  Badge,
  Box,
  Burger,
  Button,
  Group,
  ScrollArea,
  SegmentedControl,
  Skeleton,
  Stack,
  Text,
  Tooltip,
  UnstyledButton,
  useComputedColorScheme,
  useMantineColorScheme,
} from '@mantine/core'
import { useDisclosure } from '@mantine/hooks'
import {
  IconBook2,
  IconCalendarEvent,
  IconCalendarRepeat,
  IconAddressBook,
  IconChartBar,
  IconClock,
  IconCreditCard,
  IconDental,
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
import { apiAssetUrl, apiFetch } from '../../api/client'
import type { BusinessRead, InboxSummary, PlanRead } from '../../api/types'
import { usePolling } from './inbox/usePolling'
import StatusBadge from '../../components/StatusBadge'

type NavIcon = ComponentType<{ size?: number; stroke?: number }>
type NavItem = { label: string; to: string; icon: NavIcon; tint: string; ownerAdminOnly?: boolean; alsoActiveOn?: string[] }

// Grouped the way people think about their day, each item with its own colour tile (macOS System Settings style),
// so a page can be found by colour and shape as well as by reading its name.
const NAV_GROUPS: { title: string; items: NavItem[] }[] = [
  {
    title: 'Daily work',
    items: [
      { label: 'Overview', to: '/dashboard', icon: IconLayoutDashboard, tint: 'linear-gradient(135deg,#8B5CF6,#6D28D9)' },
      { label: 'Inbox', to: '/dashboard/inbox', icon: IconInbox, tint: 'linear-gradient(135deg,#38BDF8,#2563EB)' },
      { label: 'Appointments', to: '/dashboard/appointments', icon: IconCalendarEvent, tint: 'linear-gradient(135deg,#F472B6,#DB2777)' },
      { label: 'Customers', to: '/dashboard/customers', icon: IconAddressBook, tint: 'linear-gradient(135deg,#FDBA74,#EA580C)' },
      { label: 'Check-in Scanner', to: '/dashboard/checkin', icon: IconQrcode, tint: 'linear-gradient(135deg,#2DD4BF,#0D9488)' },
    ],
  },
  {
    title: 'Your business',
    items: [
      { label: 'Services', to: '/dashboard/services', icon: IconDental, tint: 'linear-gradient(135deg,#67E8F9,#0891B2)' },
      { label: 'Staff', to: '/dashboard/staff', icon: IconUsers, tint: 'linear-gradient(135deg,#A5B4FC,#4F46E5)' },
      { label: 'Business Hours', to: '/dashboard/hours', icon: IconClock, tint: 'linear-gradient(135deg,#FCD34D,#D97706)' },
      { label: 'Payments', to: '/dashboard/payments', icon: IconCreditCard, tint: 'linear-gradient(135deg,#6EE7B7,#059669)' },
    ],
  },
  {
    title: 'AI assistant',
    items: [
      { label: 'Knowledge Base', to: '/dashboard/knowledge', icon: IconBook2, tint: 'linear-gradient(135deg,#E879F9,#A21CAF)' },
      { label: 'AI Training Room', to: '/dashboard/training', icon: IconSparkles, tint: 'linear-gradient(135deg,#C084FC,#7C3AED)' },
      { label: 'Follow-ups', to: '/dashboard/followups', icon: IconRepeat, tint: 'linear-gradient(135deg,#BEF264,#65A30D)' },
    ],
  },
  {
    title: 'Insights',
    items: [
      { label: 'Reports & trends', to: '/dashboard/reports', icon: IconChartBar, tint: 'linear-gradient(135deg,#93C5FD,#1D4ED8)', alsoActiveOn: ['/dashboard/analytics'] },
    ],
  },
  {
    title: 'Connections',
    items: [
      { label: 'Channels', to: '/dashboard/channels', icon: IconPlugConnected, tint: 'linear-gradient(135deg,#5EEAD4,#0F766E)', ownerAdminOnly: true },
      { label: 'Website chat', to: '/dashboard/widget', icon: IconMessageCircle, tint: 'linear-gradient(135deg,#7DD3FC,#0284C7)' },
      { label: 'Google Calendar', to: '/dashboard/google-calendar', icon: IconCalendarRepeat, tint: 'linear-gradient(135deg,#FCA5A5,#DC2626)' },
    ],
  },
]

const SETTINGS_ITEM: NavItem = {
  label: 'Settings',
  to: '/dashboard/settings',
  icon: IconSettings,
  tint: 'linear-gradient(135deg,#CBD5E1,#64748B)',
}

// Screens are keyed by their section (e.g. /dashboard/inbox), so switching conversations inside the inbox doesn't
// replay the page entrance.
function sectionKey(pathname: string) {
  return pathname.split('/').slice(0, 3).join('/')
}

function greeting() {
  const h = new Date().getHours()
  return h < 12 ? 'Good morning' : h < 17 ? 'Good afternoon' : 'Good evening'
}

function ThemeSwitch() {
  const { setColorScheme } = useMantineColorScheme()
  const computed = useComputedColorScheme('light')
  return (
    <SegmentedControl
      size="xs"
      aria-label="Colour theme"
      value={computed}
      onChange={(v) => setColorScheme(v as 'light' | 'dark')}
      data={[
        {
          value: 'light',
          label: (
            <Group gap={6} wrap="nowrap" px={2}>
              <IconSun size={16} stroke={1.9} />
              <span>Light</span>
            </Group>
          ),
        },
        {
          value: 'dark',
          label: (
            <Group gap={6} wrap="nowrap" px={2}>
              <IconMoon size={16} stroke={1.9} />
              <span>Dark</span>
            </Group>
          ),
        },
      ]}
    />
  )
}

function NavEntry({ item, active, badge, onClick }: { item: NavItem; active: boolean; badge?: number; onClick: () => void }) {
  const Icon = item.icon
  return (
    <UnstyledButton
      component={NavLink}
      to={item.to}
      end={item.to === '/dashboard'}
      onClick={onClick}
      className="ng-nav-item"
      data-active={active || undefined}
      aria-current={active ? 'page' : undefined}
    >
      <span className="ng-tile ng-nav-tile" style={{ background: item.tint }}>
        <Icon size={17} stroke={2} />
      </span>
      <span className="ng-nav-label">{item.label}</span>
      {!!badge && badge > 0 && (
        <Badge className="ng-nav-badge" size="md" circle variant="filled" color="orange">
          {badge}
        </Badge>
      )}
    </UnstyledButton>
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

  const isActive = (item: NavItem) =>
    item.to === '/dashboard'
      ? pathname === item.to
      : pathname.startsWith(item.to) ||
        (item.alsoActiveOn ?? []).some((p) => pathname.startsWith(p)) ||
        (item.to === '/dashboard/inbox' && pathname.startsWith('/dashboard/handoffs'))
  const initials = (business?.name ?? '')
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase())
    .join('')

  return (
    <AppShell
      layout="alt"
      header={{ height: 72 }}
      navbar={{ width: 284, breakpoint: 'sm', collapsed: { mobile: !opened } }}
      padding={{ base: 'md', sm: 'xl' }}
    >
      <AppShell.Header withBorder={false}>
        <Group h="100%" px={{ base: 'md', sm: 'xl' }} justify="space-between" wrap="nowrap" className="ng-topbar">
          <Group gap="sm" wrap="nowrap" style={{ minWidth: 0 }}>
            <Burger opened={opened} onClick={toggle} hiddenFrom="sm" size="sm" aria-label="Open menu" />
            <div style={{ minWidth: 0 }}>
              <Text fw={800} fz={{ base: 'md', sm: 'lg' }} lh={1.2} truncate>
                {greeting()}
              </Text>
              <Text size="sm" c="dimmed" visibleFrom="xs" lh={1.3}>
                {new Intl.DateTimeFormat(undefined, { weekday: 'long', day: 'numeric', month: 'long' }).format(new Date())}
              </Text>
            </div>
          </Group>
          <Group gap="sm" wrap="nowrap">
            <div className="ng-theme-switch">
              <ThemeSwitch />
            </div>
            <Tooltip label="Sign out of the dashboard">
              <Button
                variant="default"
                size="sm"
                radius="xl"
                leftSection={<IconLogout size={17} stroke={1.9} />}
                onClick={handleLogout}
                aria-label="Log out"
              >
                <Text span size="sm" fw={600} visibleFrom="xs">
                  Log out
                </Text>
              </Button>
            </Tooltip>
          </Group>
        </Group>
      </AppShell.Header>

      <AppShell.Navbar p="md" withBorder={false} className="ng-sidebar">
        <AppShell.Section>
          <Group gap={12} wrap="nowrap" px={6} pt={4} pb="md">
            <span className="ng-tile ng-logo">
              <IconMoonStars size={21} stroke={1.9} />
            </span>
            <div style={{ flex: 1, minWidth: 0 }}>
              <Text fw={800} fz="lg" lh={1.15} className="ng-gradient-text">
                Night Guard AI
              </Text>
              <Text size="xs" c="dimmed" fw={500}>
                Business dashboard
              </Text>
            </div>
            <Burger opened={opened} onClick={toggle} hiddenFrom="sm" size="sm" aria-label="Close menu" />
          </Group>

          <div className="ng-business-card">
            <Avatar radius="xl" size={42} className="ng-avatar" src={apiAssetUrl(business?.logo_url)} alt="">
              {initials || '·'}
            </Avatar>
            <Stack gap={2} style={{ minWidth: 0, flex: 1 }}>
              {business ? (
                <Text fw={700} size="sm" truncate>
                  {business.name}
                </Text>
              ) : (
                <Skeleton height={14} width="80%" />
              )}
              {plan ? <StatusBadge status={plan.plan} size="sm" /> : <Skeleton height={16} width={60} radius="xl" />}
            </Stack>
          </div>
        </AppShell.Section>

        <AppShell.Section grow component={ScrollArea} type="auto" scrollbarSize={6} mt="md" mx={-6} px={6}>
          <Stack gap="md" pb="sm">
            {NAV_GROUPS.map((group) => {
              const items = group.items.filter((item) => !item.ownerAdminOnly || canAccessOwnerAdminOnly)
              if (items.length === 0) return null
              return (
                <div key={group.title}>
                  <Text className="ng-nav-group">{group.title}</Text>
                  <Stack gap={2}>
                    {items.map((item) => (
                      <NavEntry
                        key={item.to}
                        item={item}
                        active={isActive(item)}
                        badge={item.to === '/dashboard/inbox' ? waiting : undefined}
                        onClick={close}
                      />
                    ))}
                  </Stack>
                </div>
              )
            })}
          </Stack>
        </AppShell.Section>

        <AppShell.Section pt="sm" className="ng-sidebar-foot">
          <Box hiddenFrom="xs" mb="xs" px={4}>
            <ThemeSwitch />
          </Box>
          <NavEntry item={SETTINGS_ITEM} active={isActive(SETTINGS_ITEM)} onClick={close} />
        </AppShell.Section>
      </AppShell.Navbar>

      <AppShell.Main>
        <div key={sectionKey(pathname)} className="ng-page" style={{ maxWidth: 1280, margin: '0 auto' }}>
          <Outlet context={{ business, plan }} />
        </div>
      </AppShell.Main>
    </AppShell>
  )
}
