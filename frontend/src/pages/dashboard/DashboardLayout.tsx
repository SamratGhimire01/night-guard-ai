import { useEffect, useState } from 'react'
import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { AppShell, Badge, Burger, Group, NavLink as MantineNavLink, Skeleton, Stack, Text, UnstyledButton } from '@mantine/core'
import { useDisclosure } from '@mantine/hooks'
import { useAuth } from '../../auth/AuthContext'
import { apiFetch } from '../../api/client'
import type { BusinessRead, PlanRead } from '../../api/types'

const NAV_SECTIONS: { label: string; to: string; icon: string; ownerAdminOnly?: boolean }[] = [
  { label: 'Overview', to: '/dashboard', icon: '🏠' },
  { label: 'Appointments', to: '/dashboard/appointments', icon: '📅' },
  { label: 'Services', to: '/dashboard/services', icon: '🦷' },
  { label: 'Staff', to: '/dashboard/staff', icon: '👥' },
  { label: 'Business Hours', to: '/dashboard/hours', icon: '🕐' },
  { label: 'Knowledge Base', to: '/dashboard/knowledge', icon: '📚' },
  { label: 'AI Training Room', to: '/dashboard/training', icon: '🎯' },
  { label: 'Human Handoffs', to: '/dashboard/handoffs', icon: '🧑‍💼' },
  { label: 'Reports', to: '/dashboard/reports', icon: '📊' },
  { label: 'Follow-ups', to: '/dashboard/followups', icon: '🔁' },
  { label: 'Website Widget', to: '/dashboard/widget', icon: '💬' },
  { label: 'Google Calendar', to: '/dashboard/google-calendar', icon: '📆' },
  { label: 'Channels', to: '/dashboard/channels', icon: '🔌', ownerAdminOnly: true },
  { label: 'Settings', to: '/dashboard/settings', icon: '⚙️' },
]

export default function DashboardLayout() {
  const [opened, { toggle }] = useDisclosure()
  const { logout, role } = useAuth()
  const canAccessOwnerAdminOnly = role === 'owner' || role === 'admin'
  const navigate = useNavigate()
  const [business, setBusiness] = useState<BusinessRead | null>(null)
  const [plan, setPlan] = useState<PlanRead | null>(null)

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
      navbar={{ width: 240, breakpoint: 'sm', collapsed: { mobile: !opened } }}
      padding="lg"
    >
      <AppShell.Header>
        <Group h="100%" px="md" justify="space-between">
          <Group>
            <Burger opened={opened} onClick={toggle} hiddenFrom="sm" size="sm" />
            <Text fw={700}>Night Guard AI</Text>
          </Group>
          <Group>
            {business ? (
              <Text fw={600} size="sm">
                {business.name}
              </Text>
            ) : (
              <Skeleton height={16} width={140} />
            )}
            {plan ? (
              <Badge color={plan.plan === 'premium' ? 'grape' : 'gray'} variant="light" tt="capitalize">
                {plan.plan}
              </Badge>
            ) : (
              <Skeleton height={20} width={60} radius="xl" />
            )}
            <UnstyledButton onClick={handleLogout} fz="sm" fw={600} c="red">
              Log out
            </UnstyledButton>
          </Group>
        </Group>
      </AppShell.Header>

      <AppShell.Navbar p="md">
        <Stack gap={2}>
          {NAV_SECTIONS.filter((item) => !item.ownerAdminOnly || canAccessOwnerAdminOnly).map((item) => (
            <MantineNavLink
              key={item.to}
              component={NavLink}
              to={item.to}
              end={item.to === '/dashboard'}
              label={item.label}
              leftSection={<span>{item.icon}</span>}
            />
          ))}
        </Stack>
      </AppShell.Navbar>

      <AppShell.Main>
        <Outlet context={{ business, plan }} />
      </AppShell.Main>
    </AppShell>
  )
}
