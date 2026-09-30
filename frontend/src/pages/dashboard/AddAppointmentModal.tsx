import { useEffect, useState } from 'react'
import { Alert, Button, Group, Modal, Select, SimpleGrid, Skeleton, Stack, Text, TextInput, UnstyledButton } from '@mantine/core'
import { notifications } from '@mantine/notifications'
import { apiFetch, ApiError } from '../../api/client'
import type { ServiceRead } from '../../api/types'

interface Props {
  opened: boolean
  onClose: () => void
  onCreated: () => void
  timezone: string
}

function todayIn(timeZone: string) {
  // en-CA formats as YYYY-MM-DD
  return new Intl.DateTimeFormat('en-CA', { timeZone }).format(new Date())
}

/** Add a booking taken by phone or at the front desk. Only real open times are offered (same calculation the
 * assistant uses in chat), so it can't double-book. */
export default function AddAppointmentModal({ opened, onClose, onCreated, timezone }: Props) {
  const [services, setServices] = useState<ServiceRead[] | null>(null)
  const [serviceId, setServiceId] = useState<string | null>(null)
  const [day, setDay] = useState(() => todayIn(timezone))
  const [slots, setSlots] = useState<string[] | null>(null)
  const [slot, setSlot] = useState<string | null>(null)
  const [name, setName] = useState('')
  const [phone, setPhone] = useState('')
  const [email, setEmail] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!opened) return
    setError(null)
    apiFetch<ServiceRead[]>('/services').then((list) => {
      setServices(list)
      setServiceId((current) => current ?? list[0]?.id ?? null)
    })
  }, [opened])

  useEffect(() => {
    setDay(todayIn(timezone))
  }, [timezone])

  useEffect(() => {
    if (!opened || !serviceId || !day) return
    let cancelled = false
    setSlots(null)
    setSlot(null)
    apiFetch<{ slots: string[] }>(`/appointments/available-slots?service_id=${serviceId}&on=${day}`)
      .then((r) => !cancelled && setSlots(r.slots))
      .catch(() => !cancelled && setSlots([]))
    return () => {
      cancelled = true
    }
  }, [opened, serviceId, day])

  const time = (iso: string) => new Date(iso).toLocaleTimeString(undefined, { timeZone: timezone, hour: 'numeric', minute: '2-digit' })

  function close() {
    setName('')
    setPhone('')
    setEmail('')
    setSlot(null)
    onClose()
  }

  async function save() {
    if (!name.trim()) return setError("Enter the customer's name.")
    if (!serviceId || !slot) return setError('Choose a service and a time.')
    setSaving(true)
    setError(null)
    try {
      const customer = await apiFetch<{ id: string }>('/customers', {
        method: 'POST',
        body: JSON.stringify({ name: name.trim(), phone: phone.trim() || null, email: email.trim() || null }),
      })
      await apiFetch('/appointments', {
        method: 'POST',
        body: JSON.stringify({ customer_id: customer.id, service_id: serviceId, scheduled_at: slot }),
      })
      notifications.show({ color: 'green', message: `Booked ${name.trim()} for ${time(slot)}.` })
      onCreated()
      close()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not save the booking. Please try again.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal opened={opened} onClose={close} title="Add an appointment" size="lg">
      <Stack gap="md">
        {error && <Alert color="red">{error}</Alert>}
        {services !== null && services.length === 0 ? (
          <Alert color="yellow">Add a service first (Services page), then you can book it here.</Alert>
        ) : (
          <>
            <SimpleGrid cols={{ base: 1, sm: 2 }}>
              <Select
                label="Service"
                data={(services ?? []).map((s) => ({ value: s.id, label: `${s.name} (${s.duration_minutes} min)` }))}
                value={serviceId}
                onChange={setServiceId}
                allowDeselect={false}
              />
              <TextInput label="Day" type="date" value={day} min={todayIn(timezone)} onChange={(e) => setDay(e.currentTarget.value)} />
            </SimpleGrid>
            <div>
              <Text fw={600} size="sm" mb={6}>
                Time
              </Text>
              {slots === null ? (
                <Skeleton height={44} />
              ) : slots.length === 0 ? (
                <Text size="sm" c="dimmed">
                  No open times on this day. Try another day, or check your opening hours.
                </Text>
              ) : (
                <SimpleGrid cols={{ base: 3, sm: 5 }} spacing="xs">
                  {slots.map((s) => (
                    <UnstyledButton key={s} className="ng-slot" data-active={slot === s || undefined} onClick={() => setSlot(s)}>
                      {time(s)}
                    </UnstyledButton>
                  ))}
                </SimpleGrid>
              )}
            </div>
            <TextInput label="Customer name" required value={name} onChange={(e) => setName(e.currentTarget.value)} />
            <SimpleGrid cols={{ base: 1, sm: 2 }}>
              <TextInput label="Phone" type="tel" value={phone} onChange={(e) => setPhone(e.currentTarget.value)} />
              <TextInput
                label="Email"
                description="Optional. They get a confirmation if you add it."
                type="email"
                value={email}
                onChange={(e) => setEmail(e.currentTarget.value)}
              />
            </SimpleGrid>
            <Group justify="flex-end">
              <Button variant="default" onClick={close}>
                Cancel
              </Button>
              <Button onClick={save} loading={saving} disabled={!slot}>
                Book
              </Button>
            </Group>
          </>
        )}
      </Stack>
    </Modal>
  )
}
