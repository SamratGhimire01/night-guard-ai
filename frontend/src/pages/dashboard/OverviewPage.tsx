import { useEffect, useState } from 'react'
import { Badge, Card, Center, Group, Loader, Paper, SimpleGrid, Stack, Table, Text, Title } from '@mantine/core'
import { Link, useOutletContext } from 'react-router-dom'
import { useAuth } from '../../auth/AuthContext'
import { apiFetch } from '../../api/client'
import type { AppointmentListItem, BusinessRead, HandoffListItem, MonthlyReport } from '../../api/types'

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

function StatCard({ label, value }: { label: string; value: string | number }) {
  return (
    <Paper withBorder p="sm" radius="md">
      <Text size="xs" c="dimmed">
        {label}
      </Text>
      <Text size="xl" fw={700}>
        {value}
      </Text>
    </Paper>
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

  return (
    <Stack gap="lg">
      <Title order={2}>Overview</Title>

      <div>
        <Text fw={600} size="sm" mb="xs">
          Today
        </Text>
        {todayAppts === null || openHandoffs === null ? (
          <Center py="md">
            <Loader size="sm" />
          </Center>
        ) : (
          <SimpleGrid cols={{ base: 2, sm: 4 }}>
            <StatCard label="Appointments today" value={todayAppts.length} />
            <StatCard
              label="Confirmed today"
              value={todayAppts.filter((a) => a.status === 'confirmed').length}
            />
            <StatCard label="Open handoffs" value={openHandoffs.length >= 200 ? '200+' : openHandoffs.length} />
            <StatCard
              label="This month scheduled"
              value={monthly === 'skip' || monthly === null ? '—' : monthly.appointments.scheduled_for_month}
            />
          </SimpleGrid>
        )}
      </div>

      {canSeeReports && (
        <div>
          <Text fw={600} size="sm" mb="xs">
            This month
          </Text>
          {monthly === null ? (
            <Center py="md">
              <Loader size="sm" />
            </Center>
          ) : monthly === 'skip' ? null : (
            <SimpleGrid cols={{ base: 2, sm: 4 }}>
              <StatCard label="Requested" value={monthly.appointments.requested} />
              <StatCard
                label="Cancellation rate"
                value={
                  monthly.cancellation_rate.value === null
                    ? 'N/A'
                    : `${(monthly.cancellation_rate.value * 100).toFixed(1)}%`
                }
              />
              <StatCard
                label="Booking conversion"
                value={
                  monthly.booking_conversion.value === null
                    ? 'N/A'
                    : `${(monthly.booking_conversion.value * 100).toFixed(1)}%`
                }
              />
              <StatCard label="Estimated billed value" value={`$${Number(monthly.revenue_estimate.value).toFixed(2)}`} />
            </SimpleGrid>
          )}
        </div>
      )}

      <div>
        <Text fw={600} size="sm" mb="xs">
          Today's appointments
        </Text>
        {todayAppts === null ? (
          <Center py="md">
            <Loader size="sm" />
          </Center>
        ) : todayAppts.length === 0 ? (
          <Text c="dimmed" size="sm">
            No appointments scheduled for today.
          </Text>
        ) : (
          <Table.ScrollContainer minWidth={500}>
            <Table striped>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>Customer</Table.Th>
                  <Table.Th>Service</Table.Th>
                  <Table.Th>Time</Table.Th>
                  <Table.Th>Status</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {todayAppts.map((a) => (
                  <Table.Tr key={a.id}>
                    <Table.Td>{a.customer_name}</Table.Td>
                    <Table.Td>{a.service_name ?? '—'}</Table.Td>
                    <Table.Td>{timeInZone(a.scheduled_at, timezone)}</Table.Td>
                    <Table.Td>
                      <Badge variant="light">{a.status}</Badge>
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
        )}
        <Text size="xs" mt={4}>
          <Link to="/dashboard/appointments">See all appointments →</Link>
        </Text>
      </div>

      <div>
        <Text fw={600} size="sm" mb="xs">
          Recent open handoffs
        </Text>
        {openHandoffs === null ? (
          <Center py="md">
            <Loader size="sm" />
          </Center>
        ) : openHandoffs.length === 0 ? (
          <Text c="dimmed" size="sm">
            No open handoffs — nothing waiting on a real person right now.
          </Text>
        ) : (
          <Stack gap="xs">
            {openHandoffs.slice(0, 5).map((h) => (
              <Card key={h.id} withBorder p="xs" radius="sm">
                <Group justify="space-between">
                  <Text size="sm" fw={600}>
                    {h.customer_name}
                  </Text>
                  <Text size="xs" c="dimmed">
                    {new Date(h.created_at).toLocaleString()}
                  </Text>
                </Group>
                <Text size="xs" c="dimmed">
                  {h.reason}
                </Text>
              </Card>
            ))}
          </Stack>
        )}
        <Text size="xs" mt={4}>
          <Link to="/dashboard/handoffs">See all handoffs →</Link>
        </Text>
      </div>
    </Stack>
  )
}
