import { useEffect, useState } from 'react'
import {
  ActionIcon,
  Button,
  Checkbox,
  Divider,
  Group,
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
import type { BusinessHourDay, BusinessHoursResponse, HolidayException } from '../../api/types'

const DAY_LABELS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']

function defaultWeek(): BusinessHourDay[] {
  return DAY_LABELS.map((_, day_of_week) => ({
    day_of_week,
    closed: day_of_week >= 5, // Sat/Sun closed by default, purely a starting point to edit
    open_time: '09:00',
    close_time: '17:00',
  }))
}

export default function HoursPage() {
  const { role } = useAuth()
  const canWrite = role === 'owner' || role === 'admin'

  const [days, setDays] = useState<BusinessHourDay[]>(defaultWeek())
  const [exceptions, setExceptions] = useState<HolidayException[]>([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)

  const [newDate, setNewDate] = useState('')
  const [newClosed, setNewClosed] = useState(true)
  const [newOpen, setNewOpen] = useState('09:00')
  const [newClose, setNewClose] = useState('17:00')

  async function load() {
    try {
      const res = await apiFetch<BusinessHoursResponse>('/business/hours')
      if (res.weekly.length === 7) {
        setDays([...res.weekly].sort((a, b) => a.day_of_week - b.day_of_week))
      }
      setExceptions(res.exceptions)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [])

  function updateDay(index: number, patch: Partial<BusinessHourDay>) {
    setDays((prev) => prev.map((d, i) => (i === index ? { ...d, ...patch } : d)))
  }

  async function handleSave() {
    setSaving(true)
    try {
      const payload = {
        days: days.map((d) => ({
          day_of_week: d.day_of_week,
          closed: d.closed,
          open_time: d.closed ? null : d.open_time,
          close_time: d.closed ? null : d.close_time,
        })),
      }
      await apiFetch('/business/hours', { method: 'PUT', body: JSON.stringify(payload) })
      notifications.show({ message: 'Business hours saved.', color: 'green' })
      await load()
    } catch (err) {
      notifications.show({ message: err instanceof ApiError ? err.message : 'Save failed.', color: 'red' })
    } finally {
      setSaving(false)
    }
  }

  async function handleAddException() {
    if (!newDate) return
    try {
      const created = await apiFetch<HolidayException>('/business/hours/exceptions', {
        method: 'POST',
        body: JSON.stringify({
          date: newDate,
          closed: newClosed,
          open_time: newClosed ? null : newOpen,
          close_time: newClosed ? null : newClose,
        }),
      })
      setExceptions((prev) => [...prev, created].sort((a, b) => a.date.localeCompare(b.date)))
      setNewDate('')
      notifications.show({ message: `Exception for ${created.date} added.`, color: 'green' })
    } catch (err) {
      notifications.show({ message: err instanceof ApiError ? err.message : 'Add failed.', color: 'red' })
    }
  }

  async function handleDeleteException(exception: HolidayException) {
    if (!window.confirm(`Remove the hours exception for ${exception.date}?`)) return
    try {
      await apiFetch(`/business/hours/exceptions/${exception.id}`, { method: 'DELETE' })
      setExceptions((prev) => prev.filter((e) => e.id !== exception.id))
    } catch (err) {
      notifications.show({ message: err instanceof ApiError ? err.message : 'Delete failed.', color: 'red' })
    }
  }

  return (
    <Stack gap="xl">
      <div>
        <Group justify="space-between" mb="sm">
          <Title order={2}>Business Hours</Title>
          {canWrite ? (
            <Button onClick={handleSave} loading={saving} disabled={loading}>
              Save weekly hours
            </Button>
          ) : (
            <Tooltip label="Owners and admins only">
              <Button disabled>Save weekly hours</Button>
            </Tooltip>
          )}
        </Group>

        <Table.ScrollContainer minWidth={500}>
          <Table verticalSpacing="sm">
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Day</Table.Th>
                <Table.Th>Closed</Table.Th>
                <Table.Th>Open</Table.Th>
                <Table.Th>Close</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {days.map((day, index) => (
                <Table.Tr key={day.day_of_week}>
                  <Table.Td>{DAY_LABELS[day.day_of_week]}</Table.Td>
                  <Table.Td>
                    <Checkbox
                      checked={day.closed}
                      disabled={!canWrite}
                      onChange={(e) => updateDay(index, { closed: e.currentTarget.checked })}
                    />
                  </Table.Td>
                  <Table.Td>
                    <input
                      type="time"
                      value={day.open_time ?? '09:00'}
                      disabled={day.closed || !canWrite}
                      onChange={(e) => updateDay(index, { open_time: e.target.value })}
                    />
                  </Table.Td>
                  <Table.Td>
                    <input
                      type="time"
                      value={day.close_time ?? '17:00'}
                      disabled={day.closed || !canWrite}
                      onChange={(e) => updateDay(index, { close_time: e.target.value })}
                    />
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      </div>

      <Divider />

      <div>
        <Title order={3} mb="sm">
          Holiday / exception dates
        </Title>

        <Table.ScrollContainer minWidth={400} mb="md">
          <Table verticalSpacing="sm">
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Date</Table.Th>
                <Table.Th>Closed</Table.Th>
                <Table.Th>Hours</Table.Th>
                <Table.Th />
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {!loading && exceptions.length === 0 && (
                <Table.Tr>
                  <Table.Td colSpan={4}>
                    <Text c="dimmed" ta="center" py="sm">
                      No exception dates.
                    </Text>
                  </Table.Td>
                </Table.Tr>
              )}
              {exceptions.map((exception) => (
                <Table.Tr key={exception.id}>
                  <Table.Td>{exception.date}</Table.Td>
                  <Table.Td>{exception.closed ? 'Yes' : 'No'}</Table.Td>
                  <Table.Td>
                    {exception.closed ? '—' : `${exception.open_time} – ${exception.close_time}`}
                  </Table.Td>
                  <Table.Td>
                    {canWrite && (
                      <ActionIcon
                        variant="subtle"
                        color="red"
                        onClick={() => handleDeleteException(exception)}
                        aria-label="Remove"
                      >
                        🗑️
                      </ActionIcon>
                    )}
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>

        {canWrite && (
          <Group align="flex-end">
            <TextInput
              label="Date"
              type="date"
              value={newDate}
              onChange={(e) => setNewDate(e.currentTarget.value)}
            />
            <Checkbox
              label="Closed all day"
              checked={newClosed}
              onChange={(e) => setNewClosed(e.currentTarget.checked)}
              mb={8}
            />
            {!newClosed && (
              <>
                <div>
                  <Text size="xs" fw={600} mb={4}>
                    Open
                  </Text>
                  <input type="time" value={newOpen} onChange={(e) => setNewOpen(e.target.value)} />
                </div>
                <div>
                  <Text size="xs" fw={600} mb={4}>
                    Close
                  </Text>
                  <input type="time" value={newClose} onChange={(e) => setNewClose(e.target.value)} />
                </div>
              </>
            )}
            <Button onClick={handleAddException} disabled={!newDate}>
              Add exception
            </Button>
          </Group>
        )}
      </div>
    </Stack>
  )
}
