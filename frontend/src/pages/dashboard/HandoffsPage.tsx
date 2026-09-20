import { useCallback, useEffect, useState } from 'react'
import { ActionIcon, Button, Group, Paper, SegmentedControl, Stack, Table, Text, Tooltip } from '@mantine/core'
import { notifications } from '@mantine/notifications'
import { IconCheck, IconHeadset } from '@tabler/icons-react'
import { apiFetch, ApiError } from '../../api/client'
import type { HandoffListItem } from '../../api/types'
import { EmptyRow } from '../../components/EmptyState'
import PageHeader from '../../components/PageHeader'
import StatusBadge from '../../components/StatusBadge'
import TableSkeleton from '../../components/TableSkeleton'

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
      <PageHeader
        title="Human Handoffs"
        description="Conversations the AI escalated to a real person — a customer asked for one, or the AI couldn't confidently help."
      />

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

      <Paper p={0} style={{ overflow: 'hidden' }}>
        <Table.ScrollContainer minWidth={600}>
          <Table>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Customer</Table.Th>
                <Table.Th visibleFrom="md">Channel</Table.Th>
                <Table.Th>Reason</Table.Th>
                <Table.Th>Created</Table.Th>
                <Table.Th>Status</Table.Th>
                <Table.Th />
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {handoffs === null ? (
                <TableSkeleton cols={6} rows={6} />
              ) : handoffs.length === 0 ? (
                <EmptyRow
                  colSpan={6}
                  icon={<IconHeadset size={22} stroke={1.75} />}
                  title={`No ${statusFilter === 'all' ? '' : statusFilter + ' '}handoffs`}
                  hint="When the AI hands a conversation to a person, it shows up here."
                />
              ) : (
                handoffs.map((h) => (
                  <Table.Tr key={h.id}>
                    <Table.Td style={{ whiteSpace: 'nowrap' }}>{h.customer_name}</Table.Td>
                    <Table.Td visibleFrom="md" style={{ textTransform: 'capitalize' }}>
                      {h.channel}
                    </Table.Td>
                    <Table.Td miw={200}>
                      <Text size="sm">{h.reason}</Text>
                    </Table.Td>
                    <Table.Td style={{ whiteSpace: 'nowrap' }}>
                      {new Date(h.created_at).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })}
                    </Table.Td>
                    <Table.Td>
                      <StatusBadge status={h.status} />
                    </Table.Td>
                    <Table.Td>
                      {h.status !== 'resolved' && (
                        <Tooltip label="Mark resolved">
                          <ActionIcon color="teal" aria-label="Mark resolved" onClick={() => resolve(h.id)}>
                            <IconCheck size={17} stroke={1.75} />
                          </ActionIcon>
                        </Tooltip>
                      )}
                    </Table.Td>
                  </Table.Tr>
                ))
              )}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      </Paper>

      <Group justify="center" gap="sm">
        <Button variant="default" disabled={page === 0} onClick={() => setPage((p) => p - 1)}>
          Previous
        </Button>
        <Text size="sm" c="dimmed">
          Page {page + 1}
        </Text>
        <Button
          variant="default"
          disabled={handoffs === null || handoffs.length < PAGE_SIZE}
          onClick={() => setPage((p) => p + 1)}
        >
          Next
        </Button>
      </Group>
    </Stack>
  )
}
