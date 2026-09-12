import { useCallback, useEffect, useState } from 'react'
import { Badge, Button, Center, Group, Loader, SegmentedControl, Stack, Table, Text, Title } from '@mantine/core'
import { notifications } from '@mantine/notifications'
import { apiFetch, ApiError } from '../../api/client'
import type { HandoffListItem } from '../../api/types'

const PAGE_SIZE = 50

export default function HandoffsPage() {
  const [statusFilter, setStatusFilter] = useState<'open' | 'resolved' | 'all'>('open')
  const [handoffs, setHandoffs] = useState<HandoffListItem[] | null>(null)
  const [page, setPage] = useState(0)

  const load = useCallback(() => {
    setHandoffs(null)
    apiFetch<HandoffListItem[]>(
      `/handoffs?status=${statusFilter}&limit=${PAGE_SIZE}&offset=${page * PAGE_SIZE}`
    ).then(setHandoffs)
  }, [statusFilter, page])

  useEffect(() => {
    load()
  }, [load])

  useEffect(() => {
    setPage(0)
  }, [statusFilter])

  async function resolve(id: string) {
    try {
      await apiFetch(`/handoffs/${id}`, { method: 'PATCH', body: JSON.stringify({ status: 'resolved' }) })
      notifications.show({ message: 'Handoff marked resolved.', color: 'green' })
      load()
    } catch (err) {
      notifications.show({ message: err instanceof ApiError ? err.message : 'Failed to resolve.', color: 'red' })
    }
  }

  return (
    <Stack gap="md">
      <Title order={2}>Human Handoffs</Title>
      <Text c="dimmed" size="sm">
        Conversations the AI escalated to a real person — a customer asked for one, or the AI couldn't confidently
        help.
      </Text>

      <SegmentedControl
        value={statusFilter}
        onChange={(v) => setStatusFilter(v as 'open' | 'resolved' | 'all')}
        data={[
          { value: 'open', label: 'Open' },
          { value: 'resolved', label: 'Resolved' },
          { value: 'all', label: 'All' },
        ]}
        w={280}
      />

      {handoffs === null ? (
        <Center py="xl">
          <Loader />
        </Center>
      ) : handoffs.length === 0 ? (
        <Text c="dimmed" ta="center" py="lg">
          No {statusFilter === 'all' ? '' : statusFilter} handoffs.
        </Text>
      ) : (
        <>
          <Table.ScrollContainer minWidth={650}>
            <Table striped highlightOnHover>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>Customer</Table.Th>
                  <Table.Th>Channel</Table.Th>
                  <Table.Th>Reason</Table.Th>
                  <Table.Th>Created</Table.Th>
                  <Table.Th>Status</Table.Th>
                  <Table.Th></Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {handoffs.map((h) => (
                  <Table.Tr key={h.id}>
                    <Table.Td>{h.customer_name}</Table.Td>
                    <Table.Td style={{ textTransform: 'capitalize' }}>{h.channel}</Table.Td>
                    <Table.Td>{h.reason}</Table.Td>
                    <Table.Td>{new Date(h.created_at).toLocaleString()}</Table.Td>
                    <Table.Td>
                      <Badge color={h.status === 'resolved' ? 'teal' : 'orange'} variant="light" miw={78}>
                        {h.status}
                      </Badge>
                    </Table.Td>
                    <Table.Td>
                      {h.status !== 'resolved' && (
                        <Button size="compact-sm" variant="light" onClick={() => resolve(h.id)}>
                          Mark resolved
                        </Button>
                      )}
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
          <Group justify="center" gap="sm">
            <Button variant="default" disabled={page === 0} onClick={() => setPage((p) => p - 1)}>
              Previous
            </Button>
            <Text size="sm" c="dimmed">
              Page {page + 1}
            </Text>
            <Button variant="default" disabled={handoffs.length < PAGE_SIZE} onClick={() => setPage((p) => p + 1)}>
              Next
            </Button>
          </Group>
        </>
      )}
    </Stack>
  )
}
