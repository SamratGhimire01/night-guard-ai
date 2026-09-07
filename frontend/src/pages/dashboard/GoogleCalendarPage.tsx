import { useEffect, useState } from 'react'
import { useOutletContext, useSearchParams } from 'react-router-dom'
import { Alert, Badge, Button, Group, Paper, Skeleton, Stack, Text, Title } from '@mantine/core'
import { notifications } from '@mantine/notifications'
import { apiFetch, ApiError } from '../../api/client'
import type { BusinessRead, GoogleCalendarAuthorizationURL, GoogleCalendarStatus, PlanRead } from '../../api/types'

type DashboardContext = { business: BusinessRead | null; plan: PlanRead | null }

const ERROR_MESSAGES: Record<string, string> = {
  missing_code_or_state: 'Google did not return the expected data. Please try connecting again.',
  invalid_or_expired_state: 'That connection attempt expired. Please try connecting again.',
  plan_required: 'This business is on the Free plan — upgrade to Premium to connect Google Calendar.',
  connection_failed: 'Google Calendar could not be connected. Please try again in a moment.',
}

export default function GoogleCalendarPage() {
  const { plan } = useOutletContext<DashboardContext>()
  const [searchParams, setSearchParams] = useSearchParams()
  const [status, setStatus] = useState<GoogleCalendarStatus | null>(null)
  const [connecting, setConnecting] = useState(false)
  const [disconnecting, setDisconnecting] = useState(false)

  function loadStatus() {
    apiFetch<GoogleCalendarStatus>('/integrations/google-calendar/status').then(setStatus)
  }

  useEffect(() => {
    loadStatus()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (searchParams.get('gcal_connected')) {
      notifications.show({ message: 'Google Calendar connected.', color: 'green' })
      loadStatus()
      setSearchParams({}, { replace: true })
    }
    const gcalError = searchParams.get('gcal_error')
    if (gcalError) {
      notifications.show({ message: ERROR_MESSAGES[gcalError] ?? 'Could not connect Google Calendar.', color: 'red' })
      setSearchParams({}, { replace: true })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams])

  async function handleConnect() {
    setConnecting(true)
    try {
      const data = await apiFetch<GoogleCalendarAuthorizationURL>('/integrations/google-calendar/connect')
      window.location.href = data.authorization_url
    } catch (err) {
      notifications.show({ message: err instanceof ApiError ? err.message : 'Could not start the connection.', color: 'red' })
      setConnecting(false)
    }
  }

  async function handleDisconnect() {
    setDisconnecting(true)
    try {
      const updated = await apiFetch<GoogleCalendarStatus>('/integrations/google-calendar/disconnect', { method: 'POST' })
      setStatus(updated)
      notifications.show({ message: 'Google Calendar disconnected.', color: 'green' })
    } catch (err) {
      notifications.show({ message: err instanceof ApiError ? err.message : 'Disconnect failed.', color: 'red' })
    } finally {
      setDisconnecting(false)
    }
  }

  const isPremium = plan?.plan === 'premium'

  return (
    <Stack gap="md" maw={560}>
      <Title order={2}>Google Calendar</Title>
      <Text c="dimmed" size="sm">
        Connect your real Google Calendar so Night Guard treats your existing busy time as unavailable when
        proposing appointment slots, and reflects every booking, cancellation, and reschedule back into your
        calendar automatically.
      </Text>

      {!isPremium && (
        <Alert color="grape" title="Upgrade to Premium" variant="light">
          Google Calendar sync is a Premium-plan feature. Ask an owner on your team to upgrade the business's plan
          to connect a calendar.
        </Alert>
      )}

      {status === null ? (
        <Skeleton height={120} />
      ) : (
        <Paper withBorder p="md" radius="md">
          <Group justify="space-between">
            <div>
              <Group gap="xs" mb={4}>
                <Text fw={600}>Status</Text>
                <Badge color={status.connected ? 'green' : 'gray'} variant="light">
                  {status.connected ? 'Connected' : 'Not connected'}
                </Badge>
              </Group>
              {status.connected && (
                <Text size="sm" c="dimmed">
                  {status.calendar_name}
                </Text>
              )}
            </div>
            {status.connected ? (
              <Button color="red" variant="light" loading={disconnecting} onClick={handleDisconnect}>
                Disconnect
              </Button>
            ) : (
              <Button disabled={!isPremium} loading={connecting} onClick={handleConnect}>
                Connect Google Calendar
              </Button>
            )}
          </Group>
        </Paper>
      )}

      <Text size="xs" c="dimmed">
        Availability checks are pull-based — Night Guard queries Google Calendar fresh each time it proposes slots.
        Editing an event directly in Google Calendar does not push a real-time update to Night Guard; it's picked
        up the next time availability is checked.
      </Text>
    </Stack>
  )
}
