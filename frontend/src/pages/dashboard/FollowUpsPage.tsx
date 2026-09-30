import { useEffect, useState } from 'react'
import { Badge, Button, Card, Group, Skeleton, Stack, Switch, Table, Text, Title, Tooltip } from '@mantine/core'
import { notifications } from '@mantine/notifications'
import PageHeader from '../../components/PageHeader'
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
    <Stack gap="lg" maw={720}>
      <PageHeader
        title="Follow-ups"
        description="Win back customers who were interested but went quiet. Night Guard sends them one friendly email, so you don't have to remember to."
      />

      <Card p="lg">
        <Group justify="space-between" wrap="nowrap" align="flex-start" gap="lg">
          <div>
            <Text fw={700}>Send follow-ups automatically</Text>
            <Text size="sm" c="dimmed" mt={4}>
              {business.follow_ups_enabled
                ? 'On. Every 15 minutes Night Guard looks for customers who asked about a service or price and then did not reply for a day, and sends each one a single email.'
                : 'Off. Turn this on and customers who showed interest but went quiet get one friendly email.'}
            </Text>
          </div>
          {canWrite ? (
            <Switch
              size="lg"
              aria-label="Send follow-ups automatically"
              checked={business.follow_ups_enabled}
              onChange={(e) => toggle(e.currentTarget.checked)}
            />
          ) : (
            <Tooltip label="Only owners and admins can change this">
              <Switch size="lg" checked={business.follow_ups_enabled} disabled />
            </Tooltip>
          )}
        </Group>
      </Card>

      <Card p="lg">
        <Group justify="space-between" align="center" wrap="wrap" gap="md">
          <div style={{ flex: '1 1 260px' }}>
            <Text fw={700}>Check now</Text>
            <Text size="sm" c="dimmed" mt={4}>
              Don't want to wait for the next automatic check? Send any follow-ups that are due right away. Nobody ever
              gets more than one.
            </Text>
          </div>
          {canWrite ? (
            <Tooltip label="Turn follow-ups on first" disabled={business.follow_ups_enabled}>
              <Button variant="default" onClick={runNow} loading={running} disabled={!business.follow_ups_enabled}>
                Check now
              </Button>
            </Tooltip>
          ) : (
            <Tooltip label="Only owners and admins can do this">
              <Button variant="default" disabled>
                Check now
              </Button>
            </Tooltip>
          )}
        </Group>
      </Card>

      {lastRun && (
        <Card withBorder radius="md" p="md">
          <Text fw={600} size="sm" mb="xs">
            Last check: {lastRun.processed} {lastRun.processed === 1 ? 'conversation' : 'conversations'} looked at
          </Text>
          {lastRun.processed === 0 ? (
            <Text size="sm" c="dimmed">
              Nobody needs a follow-up right now.
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
