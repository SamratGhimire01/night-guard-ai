import { useEffect, useState } from 'react'
import { Anchor, Group, Paper, SimpleGrid, Skeleton, Stack, Table, Text, Title } from '@mantine/core'
import {
  IconCalendarEvent,
  IconCalendarOff,
  IconCalendarStats,
  IconCash,
  IconCircleCheck,
  IconClipboardList,
  IconHeadset,
  IconTrendingUp,
} from '@tabler/icons-react'
import { Link, useOutletContext } from 'react-router-dom'
import { useAuth } from '../../auth/AuthContext'
import { apiFetch } from '../../api/client'
import type { AppointmentListItem, BusinessRead, HandoffListItem, MonthlyReport } from '../../api/types'
import EmptyState from '../../components/EmptyState'
import PageHeader from '../../components/PageHeader'
import SetupChecklist from '../../components/SetupChecklist'
import StatCard from '../../components/StatCard'
import StatusBadge from '../../components/StatusBadge'
import TableSkeleton from '../../components/TableSkeleton'
import { friendlyDateTime } from '../../lib/dates'

type DashboardContext = { business: BusinessRead | null }

function todayStr() {
  return new Date().toISOString().slice(0, 10)
}
function thisMonthStr() {
  return new Date().toISOString().slice(0, 7)
}
function timeInZone(iso: string, timeZone: string) {
  return new Intl.DateTimeFormat('en-US', { timeZone, hour: 'numeric', minute: '2-digit' }).format(new Date(iso))
}

const ICON = { size: 20, stroke: 1.75 }

function StatGridSkeleton() {
  return (
    <SimpleGrid cols={{ base: 2, sm: 4 }}>
      {[0, 1, 2, 3].map((i) => (
        <Skeleton key={i} height={96} radius="md" />
      ))}
    </SimpleGrid>
  )
}

function SectionHeader({ title, to, linkLabel }: { title: string; to?: string; linkLabel?: string }) {
  return (
    <Group justify="space-between" mb="sm">
      <Title order={3}>{title}</Title>
      {to && (
        <Anchor component={Link} to={to} size="sm">
          {linkLabel} →
        </Anchor>
      )}
    </Group>
  )
}

export default function OverviewPage() {
  const { role } = useAuth()
  const { business } = useOutletContext<DashboardContext>()
  const timezone = business?.timezone ?? 'UTC'
  const canSeeReports = role === 'owner' || role === 'admin'

  const [todayAppts, setTodayAppts] = useState<AppointmentListItem[] | null>(null)
  const [monthly, setMonthly] = useState<MonthlyReport | null | 'skip'>(null)
  const [openHandoffs, setOpenHandoffs] = useState<HandoffListItem[] | null>(null)

  useEffect(() => {
    const today = todayStr()
    apiFetch<AppointmentListItem[]>(`/appointments?date_from=${today}&date_to=${today}&limit=50`).then(
      setTodayAppts
    )
    apiFetch<HandoffListItem[]>('/handoffs?status=open&limit=200').then(setOpenHandoffs)
    if (canSeeReports) {
      const [y, m] = thisMonthStr().split('-')
      apiFetch<MonthlyReport>(`/reports/monthly?year=${y}&month=${Number(m)}`).then(setMonthly)
    } else {
      setMonthly('skip')
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [canSeeReports])

  const money = (value: string) =>
    new Intl.NumberFormat(undefined, { style: 'currency', currency: business?.currency ?? 'USD', maximumFractionDigits: 0 }).format(Number(value))

  return (
    <Stack gap="xl">
      <PageHeader title="Overview" description="Today's activity and this month at a glance." />

      <SetupChecklist />

      <div>
        <SectionHeader title="Today" />
        {todayAppts === null || openHandoffs === null ? (
          <StatGridSkeleton />
        ) : (
          <SimpleGrid cols={{ base: 2, sm: 4 }}>
            <StatCard label="Appointments today" value={todayAppts.length} icon={<IconCalendarEvent {...ICON} />} />
            <StatCard
              label="Confirmed today"
              value={todayAppts.filter((a) => a.status === 'confirmed').length}
              icon={<IconCircleCheck {...ICON} />}
              color="teal"
            />
            <StatCard
              label="Open handoffs"
              value={openHandoffs.length >= 200 ? '200+' : openHandoffs.length}
              icon={<IconHeadset {...ICON} />}
              color="orange"
            />
            <StatCard
              label="This month scheduled"
              value={monthly === 'skip' || monthly === null ? '—' : monthly.appointments.scheduled_for_month}
              icon={<IconCalendarStats {...ICON} />}
            />
          </SimpleGrid>
        )}
      </div>

      {canSeeReports && (
        <div>
          <SectionHeader title="This month" />
          {monthly === null ? (
            <StatGridSkeleton />
          ) : monthly === 'skip' ? null : (
            <SimpleGrid cols={{ base: 2, sm: 4 }}>
              <StatCard label="Requested" value={monthly.appointments.requested} icon={<IconClipboardList {...ICON} />} />
              <StatCard
                label="Cancellation rate"
                value={
                  monthly.cancellation_rate.value === null
                    ? 'N/A'
                    : `${(monthly.cancellation_rate.value * 100).toFixed(1)}%`
                }
                icon={<IconCalendarOff {...ICON} />}
                color="red"
              />
              <StatCard
                label="Booking conversion"
                value={
                  monthly.booking_conversion.value === null
                    ? 'N/A'
                    : `${(monthly.booking_conversion.value * 100).toFixed(1)}%`
                }
                icon={<IconTrendingUp {...ICON} />}
                color="teal"
              />
              <StatCard
                label="Estimated billed value"
                value={money(monthly.revenue_estimate.value)}
                icon={<IconCash {...ICON} />}
                color="teal"
              />
            </SimpleGrid>
          )}
        </div>
      )}

      <div>
        <SectionHeader title="Today's appointments" to="/dashboard/appointments" linkLabel="See all appointments" />
        <Paper p={0} style={{ overflow: 'hidden' }}>
          <Table.ScrollContainer minWidth={500}>
            <Table>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>Customer</Table.Th>
                  <Table.Th>Service</Table.Th>
                  <Table.Th>Time</Table.Th>
                  <Table.Th>Status</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {todayAppts === null ? (
                  <TableSkeleton cols={4} rows={3} />
                ) : todayAppts.length === 0 ? (
                  <Table.Tr>
                    <Table.Td colSpan={4}>
                      <EmptyState
                        icon={<IconCalendarEvent {...ICON} />}
                        title="No appointments today"
                        hint="New bookings from your channels will show up here."
                      />
                    </Table.Td>
                  </Table.Tr>
                ) : (
                  todayAppts.map((a) => (
                    <Table.Tr key={a.id}>
                      <Table.Td>{a.customer_name}</Table.Td>
                      <Table.Td>{a.service_name ?? '—'}</Table.Td>
                      <Table.Td style={{ whiteSpace: 'nowrap' }}>{timeInZone(a.scheduled_at, timezone)}</Table.Td>
                      <Table.Td>
                        <StatusBadge status={a.status} />
                      </Table.Td>
                    </Table.Tr>
                  ))
                )}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
        </Paper>
      </div>

      <div>
        <SectionHeader title="Recent open handoffs" to="/dashboard/handoffs" linkLabel="See all handoffs" />
        {openHandoffs === null ? (
          <Stack gap="xs">
            {[0, 1, 2].map((i) => (
              <Skeleton key={i} height={62} radius="md" />
            ))}
          </Stack>
        ) : openHandoffs.length === 0 ? (
          <Paper>
            <EmptyState
              icon={<IconHeadset {...ICON} />}
              title="No open handoffs"
              hint="No customer is waiting for your team right now."
            />
          </Paper>
        ) : (
          <Stack gap="xs">
            {openHandoffs.slice(0, 5).map((h) => (
              <Paper key={h.id} p="sm">
                <Group justify="space-between" wrap="nowrap" align="flex-start">
                  <Text size="sm" fw={600}>
                    {h.customer_name}
                  </Text>
                  <Text size="xs" c="dimmed" style={{ whiteSpace: 'nowrap' }}>
                    {friendlyDateTime(h.created_at)}
                  </Text>
                </Group>
                <Text size="sm" c="dimmed" mt={2}>
                  {h.reason}
                </Text>
              </Paper>
            ))}
          </Stack>
        )}
      </div>
    </Stack>
  )
}
