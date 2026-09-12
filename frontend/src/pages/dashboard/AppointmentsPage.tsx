import { useCallback, useEffect, useState } from 'react'
import {
  Badge,
  Button,
  Center,
  Group,
  Loader,
  Modal,
  Select,
  Stack,
  Table,
  Text,
  TextInput,
  Title,
  Tooltip,
} from '@mantine/core'
import { notifications } from '@mantine/notifications'
import { useAuth } from '../../auth/AuthContext'
import { apiFetch, ApiError } from '../../api/client'
import type { AppointmentListItem, AppointmentStatus, BusinessRead } from '../../api/types'

const STATUS_COLORS: Record<AppointmentStatus, string> = {
  pending: 'yellow',
  confirmed: 'blue',
  cancelled: 'red',
  completed: 'teal',
}
const CANCELLABLE: AppointmentStatus[] = ['pending', 'confirmed']
const PAGE_SIZE = 20

// Reschedule dates/times are entered as the BUSINESS's own wall-clock time,
// never the viewer's browser timezone — a business owner checking their
// dashboard from a different timezone than their business operates in would
// otherwise silently reschedule to the wrong real hour. Native Intl only, no
// date library: the standard "round-trip through a UTC guess" technique.
function offsetMinutesForZone(timeZone: string, atUtc: Date): number {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone,
    hour12: false,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
    .formatToParts(atUtc)
    .reduce((acc, p) => ({ ...acc, [p.type]: p.value }), {} as Record<string, string>)
  const asUtc = Date.UTC(+parts.year, +parts.month - 1, +parts.day, +parts.hour, +parts.minute, +parts.second)
  return Math.round((asUtc - atUtc.getTime()) / 60000)
}

function zonedWallClockToUtcIso(dateStr: string, timeStr: string, timeZone: string): string {
  const naiveUtcGuess = new Date(`${dateStr}T${timeStr}:00Z`)
  const offsetMin = offsetMinutesForZone(timeZone, naiveUtcGuess)
  return new Date(naiveUtcGuess.getTime() - offsetMin * 60000).toISOString()
}

function utcIsoToZonedParts(iso: string, timeZone: string): { date: string; time: string } {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone,
    hour12: false,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
    .formatToParts(new Date(iso))
    .reduce((acc, p) => ({ ...acc, [p.type]: p.value }), {} as Record<string, string>)
  return { date: `${parts.year}-${parts.month}-${parts.day}`, time: `${parts.hour}:${parts.minute}` }
}

export default function AppointmentsPage() {
  const { role } = useAuth()
  const canWrite = role === 'owner' || role === 'admin'

  const [appointments, setAppointments] = useState<AppointmentListItem[] | null>(null)
  const [timezone, setTimezone] = useState('UTC')
  const [statusFilter, setStatusFilter] = useState<string | null>(null)
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [page, setPage] = useState(0)
  const [rescheduling, setRescheduling] = useState<AppointmentListItem | null>(null)
  const [rescheduleDate, setRescheduleDate] = useState('')
  const [rescheduleTime, setRescheduleTime] = useState('')

  useEffect(() => {
    apiFetch<BusinessRead>('/business/me').then((b) => setTimezone(b.timezone))
  }, [])

  const load = useCallback(() => {
    setAppointments(null)
    const params = new URLSearchParams()
    if (statusFilter) params.set('status', statusFilter)
    if (dateFrom) params.set('date_from', dateFrom)
    if (dateTo) params.set('date_to', dateTo)
    params.set('limit', String(PAGE_SIZE))
    params.set('offset', String(page * PAGE_SIZE))
    apiFetch<AppointmentListItem[]>(`/appointments?${params.toString()}`).then(setAppointments)
  }, [statusFilter, dateFrom, dateTo, page])

  useEffect(() => {
    load()
  }, [load])

  useEffect(() => {
    setPage(0)
  }, [statusFilter, dateFrom, dateTo])

  async function handleCancel(appt: AppointmentListItem) {
    const { date, time } = utcIsoToZonedParts(appt.scheduled_at, timezone)
    if (
      !window.confirm(
        `Cancel the appointment for "${appt.customer_name}" (${date} ${time})? This cannot be undone.`
      )
    )
      return
    try {
      await apiFetch(`/appointments/${appt.id}/cancel`, { method: 'PATCH' })
      notifications.show({ message: 'Appointment cancelled.', color: 'green' })
      load()
    } catch (err) {
      notifications.show({ message: err instanceof ApiError ? err.message : 'Cancel failed.', color: 'red' })
    }
  }

  function openReschedule(appt: AppointmentListItem) {
    setRescheduling(appt)
    const { date, time } = utcIsoToZonedParts(appt.scheduled_at, timezone)
    setRescheduleDate(date)
    setRescheduleTime(time)
  }

  async function handleReschedule() {
    if (!rescheduling || !rescheduleDate || !rescheduleTime) return
    try {
      await apiFetch(`/appointments/${rescheduling.id}/reschedule`, {
        method: 'PATCH',
        body: JSON.stringify({ scheduled_at: zonedWallClockToUtcIso(rescheduleDate, rescheduleTime, timezone) }),
      })
      notifications.show({ message: 'Appointment rescheduled.', color: 'green' })
      setRescheduling(null)
      load()
    } catch (err) {
      notifications.show({ message: err instanceof ApiError ? err.message : 'Reschedule failed.', color: 'red' })
    }
  }

  return (
    <Stack gap="md">
      <Title order={2}>Appointments</Title>

      <Group gap="sm" wrap="wrap">
        <Select
          label="Status"
          placeholder="All statuses"
          clearable
          data={[
            { value: 'pending', label: 'Pending' },
            { value: 'confirmed', label: 'Confirmed' },
            { value: 'cancelled', label: 'Cancelled' },
            { value: 'completed', label: 'Completed' },
          ]}
          value={statusFilter}
          onChange={setStatusFilter}
          w={180}
        />
        <TextInput label="From" type="date" value={dateFrom} onChange={(e) => setDateFrom(e.currentTarget.value)} />
        <TextInput label="To" type="date" value={dateTo} onChange={(e) => setDateTo(e.currentTarget.value)} />
      </Group>

      {appointments === null ? (
        <Center py="xl">
          <Loader />
        </Center>
      ) : (
        <>
          <Table.ScrollContainer minWidth={700}>
            <Table striped highlightOnHover>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>Customer</Table.Th>
                  <Table.Th>Service</Table.Th>
                  <Table.Th>Time</Table.Th>
                  <Table.Th>Status</Table.Th>
                  <Table.Th></Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {appointments.map((appt) => {
                  const cancellable = CANCELLABLE.includes(appt.status)
                  return (
                    <Table.Tr key={appt.id}>
                      <Table.Td>{appt.customer_name}</Table.Td>
                      <Table.Td>{appt.service_name ?? '—'}</Table.Td>
                      <Table.Td>
                        {(() => {
                          const { date, time } = utcIsoToZonedParts(appt.scheduled_at, timezone)
                          return `${date} ${time}`
                        })()}
                      </Table.Td>
                      <Table.Td>
                        <Badge color={STATUS_COLORS[appt.status]} variant="light">
                          {appt.status}
                        </Badge>
                      </Table.Td>
                      <Table.Td>
                        {canWrite ? (
                          <Group gap="xs" wrap="nowrap">
                            <Button
                              size="compact-sm"
                              variant="light"
                              disabled={!cancellable}
                              onClick={() => openReschedule(appt)}
                            >
                              Reschedule
                            </Button>
                            <Button
                              size="compact-sm"
                              color="red"
                              variant="light"
                              disabled={!cancellable}
                              onClick={() => handleCancel(appt)}
                            >
                              Cancel
                            </Button>
                          </Group>
                        ) : (
                          <Tooltip label="Owners and admins only">
                            <Text size="xs" c="dimmed">
                              Read-only
                            </Text>
                          </Tooltip>
                        )}
                      </Table.Td>
                    </Table.Tr>
                  )
                })}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
          {appointments.length === 0 && (
            <Text c="dimmed" ta="center" py="lg">
              No appointments match these filters.
            </Text>
          )}
          <Group justify="center" gap="sm">
            <Button variant="default" disabled={page === 0} onClick={() => setPage((p) => p - 1)}>
              Previous
            </Button>
            <Text size="sm" c="dimmed">
              Page {page + 1}
            </Text>
            <Button
              variant="default"
              disabled={appointments.length < PAGE_SIZE}
              onClick={() => setPage((p) => p + 1)}
            >
              Next
            </Button>
          </Group>
        </>
      )}

      <Modal opened={!!rescheduling} onClose={() => setRescheduling(null)} title="Reschedule appointment">
        {rescheduling && (
          <Stack gap="sm">
            <Text size="sm">
              {rescheduling.customer_name} — {rescheduling.service_name ?? 'Service'}
            </Text>
            <Text size="xs" c="dimmed">
              Times below are the business's own local time ({timezone}), not your browser's.
            </Text>
            <Group grow>
              <TextInput
                label="New date"
                type="date"
                value={rescheduleDate}
                onChange={(e) => setRescheduleDate(e.currentTarget.value)}
              />
              <TextInput
                label="New time"
                type="time"
                value={rescheduleTime}
                onChange={(e) => setRescheduleTime(e.currentTarget.value)}
              />
            </Group>
            <Button onClick={handleReschedule} disabled={!rescheduleDate || !rescheduleTime}>
              Save new time
            </Button>
          </Stack>
        )}
      </Modal>
    </Stack>
  )
}
