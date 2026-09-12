import { useEffect, useState } from 'react'
import { Alert, Badge, Button, Card, Group, Skeleton, Stack, Switch, Table, Text, Title, Tooltip } from '@mantine/core'
import { notifications } from '@mantine/notifications'
import { useAuth } from '../../auth/AuthContext'
import { apiFetch, ApiError } from '../../api/client'
import type { BusinessRead } from '../../api/types'

interface FollowupResult {
  conversation_id: string
  status: string
  channel: string | null
  detail?: string
}

interface RunResponse {
  processed: number
  results: FollowupResult[]
}

export default function FollowUpsPage() {
  const { role } = useAuth()
  const canWrite = role === 'owner' || role === 'admin'

  const [business, setBusiness] = useState<BusinessRead | null>(null)
  const [running, setRunning] = useState(false)
  const [lastRun, setLastRun] = useState<RunResponse | null>(null)

  useEffect(() => {
    apiFetch<BusinessRead>('/business/me').then(setBusiness)
  }, [])

  async function toggle(enabled: boolean) {
    try {
      const updated = await apiFetch<BusinessRead>('/business/me', {
        method: 'PATCH',
        body: JSON.stringify({ follow_ups_enabled: enabled }),
      })
      setBusiness(updated)
      notifications.show({ message: `Follow-ups turned ${enabled ? 'on' : 'off'}.`, color: 'green' })
    } catch (err) {
      notifications.show({ message: err instanceof ApiError ? err.message : 'Save failed.', color: 'red' })
    }
  }

  async function runNow() {
    setRunning(true)
    setLastRun(null)
    try {
      const result = await apiFetch<RunResponse>('/followups/run', { method: 'POST' })
      setLastRun(result)
      notifications.show({
        message: `Processed ${result.processed} follow-up${result.processed === 1 ? '' : 's'}.`,
        color: 'green',
      })
    } catch (err) {
      notifications.show({ message: err instanceof ApiError ? err.message : 'Run failed.', color: 'red' })
    } finally {
      setRunning(false)
    }
  }

  if (!business) {
    return (
      <Stack gap="md">
        <Title order={2}>Follow-ups</Title>
        <Skeleton height={200} />
      </Stack>
    )
  }

  return (
    <Stack gap="lg" maw={640}>
      <Title order={2}>Follow-ups</Title>
      <Text c="dimmed" size="sm">
        When on, a customer who showed real interest (asked about pricing or a service) and then went quiet gets one
        automatic follow-up email, at most once per conversation.
      </Text>

      <Alert color="yellow" variant="light">
        This is a <strong>manual trigger</strong>, not an automatic schedule — there's no background job running
        this on its own yet. Turning follow-ups on only controls whether a run (yours, below) is allowed to send
        anything; it doesn't start a timer.
      </Alert>

      <Card withBorder radius="md" p="md">
        <Group justify="space-between">
          <div>
            <Text fw={600} size="sm">
              Follow-ups
            </Text>
            <Text size="xs" c="dimmed">
              {business.follow_ups_enabled ? 'On — a run below can send emails.' : 'Off — a run below sends nothing.'}
            </Text>
          </div>
          {canWrite ? (
            <Switch checked={business.follow_ups_enabled} onChange={(e) => toggle(e.currentTarget.checked)} />
          ) : (
            <Tooltip label="Owners and admins only">
              <Switch checked={business.follow_ups_enabled} disabled />
            </Tooltip>
          )}
        </Group>
      </Card>

      <Card withBorder radius="md" p="md">
        <Group justify="space-between" align="center">
          <div>
            <Text fw={600} size="sm">
              Run follow-ups now
            </Text>
            <Text size="xs" c="dimmed">
              Checks every open conversation for real, qualifying inactivity and sends real emails immediately.
            </Text>
          </div>
          {canWrite ? (
            <Tooltip label={business.follow_ups_enabled ? '' : 'Follow-ups are off — turn them on first.'} disabled={business.follow_ups_enabled}>
              <Button onClick={runNow} loading={running} disabled={!business.follow_ups_enabled}>
                Run now
              </Button>
            </Tooltip>
          ) : (
            <Tooltip label="Owners and admins only">
              <Button disabled>Run now</Button>
            </Tooltip>
          )}
        </Group>
      </Card>

      {lastRun && (
        <Card withBorder radius="md" p="md">
          <Text fw={600} size="sm" mb="xs">
            Last run — {lastRun.processed} processed
          </Text>
          {lastRun.processed === 0 ? (
            <Text size="sm" c="dimmed">
              No conversations currently qualify.
            </Text>
          ) : (
            <Table.ScrollContainer minWidth={500}>
              <Table>
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th>Conversation</Table.Th>
                    <Table.Th>Status</Table.Th>
                    <Table.Th>Channel</Table.Th>
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {lastRun.results.map((r) => (
                    <Table.Tr key={r.conversation_id}>
                      <Table.Td>
                        <Text size="xs" ff="monospace">
                          {r.conversation_id.slice(0, 8)}…
                        </Text>
                      </Table.Td>
                      <Table.Td>
                        <Badge color={r.status === 'sent' ? 'teal' : r.status === 'failed' ? 'red' : 'gray'} variant="light">
                          {r.status}
                        </Badge>
                      </Table.Td>
                      <Table.Td>{r.channel ?? '—'}</Table.Td>
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
            </Table.ScrollContainer>
          )}
        </Card>
      )}
    </Stack>
  )
}
