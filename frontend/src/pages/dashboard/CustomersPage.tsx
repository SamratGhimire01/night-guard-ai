import { useEffect, useState } from 'react'
import { Button, Group, Paper, Stack, Table, Text, TextInput } from '@mantine/core'
import { useDebouncedValue } from '@mantine/hooks'
import { notifications } from '@mantine/notifications'
import { IconDownload, IconSearch, IconUsers } from '@tabler/icons-react'
import { apiFetch, ApiError, downloadFile } from '../../api/client'
import { useAuth } from '../../auth/AuthContext'
import { EmptyRow } from '../../components/EmptyState'
import PageHeader from '../../components/PageHeader'
import TableSkeleton from '../../components/TableSkeleton'
import { friendlyDateTime } from '../../lib/dates'
import { channelInfo } from './inbox/format'

interface CustomerRow {
  id: string
  name: string | null
  phone: string | null
  email: string | null
  channel: string | null
  conversations: number
  appointments: number
  first_seen_at: string
  last_contact_at: string
}

const PAGE_SIZE = 50

export default function CustomersPage() {
  const { role } = useAuth()
  const canExport = role === 'owner' || role === 'admin'
  const [search, setSearch] = useState('')
  const [q] = useDebouncedValue(search, 300)
  const [rows, setRows] = useState<CustomerRow[] | null>(null)
  const [page, setPage] = useState(0)
  const [exporting, setExporting] = useState(false)

  useEffect(() => {
    let cancelled = false
    setRows(null)
    const params = new URLSearchParams({ limit: String(PAGE_SIZE), offset: String(page * PAGE_SIZE) })
    if (q.trim()) params.set('q', q.trim())
    apiFetch<CustomerRow[]>(`/customers?${params}`)
      .then((r) => !cancelled && setRows(r))
      .catch(() => !cancelled && setRows([]))
    return () => {
      cancelled = true
    }
  }, [q, page])

  async function exportCsv() {
    setExporting(true)
    try {
      await downloadFile('/customers/export.csv', 'customers.csv')
    } catch (err) {
      notifications.show({ color: 'red', message: err instanceof ApiError ? err.message : 'Could not download the file.' })
    } finally {
      setExporting(false)
    }
  }

  return (
    <Stack gap="lg">
      <PageHeader
        title="Customers"
        description="Everyone who has contacted you, on any channel, with their bookings. Most recent first."
        actions={
          canExport && (
            <Button variant="default" leftSection={<IconDownload size={18} />} onClick={exportCsv} loading={exporting}>
              Download as Excel (CSV)
            </Button>
          )
        }
      />
      <TextInput
        maw={420}
        leftSection={<IconSearch size={17} />}
        placeholder="Search by name, phone or email"
        aria-label="Search customers"
        value={search}
        onChange={(e) => {
          setSearch(e.currentTarget.value)
          setPage(0)
        }}
      />
      <Paper p={0} style={{ overflow: 'hidden' }}>
        <Table.ScrollContainer minWidth={720}>
          <Table>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Customer</Table.Th>
                <Table.Th>First contacted on</Table.Th>
                <Table.Th ta="right">Chats</Table.Th>
                <Table.Th ta="right">Bookings</Table.Th>
                <Table.Th>Last contact</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {rows === null ? (
                <TableSkeleton cols={5} />
              ) : rows.length === 0 ? (
                <EmptyRow
                  colSpan={5}
                  icon={<IconUsers size={24} stroke={1.75} />}
                  title={q ? 'No customers match your search' : 'No customers yet'}
                  hint={q ? 'Try part of their name, phone number or email.' : 'When someone messages you or books, they appear here.'}
                />
              ) : (
                rows.map((c) => {
                  const channel = c.channel ? channelInfo(c.channel) : null
                  return (
                    <Table.Tr key={c.id}>
                      <Table.Td>
                        <Text fw={600}>{c.name ?? <Text span c="dimmed" fs="italic">Name not given</Text>}</Text>
                        <Text size="sm" c="dimmed">
                          {[c.phone, c.email].filter(Boolean).join(' · ') || 'No contact details yet'}
                        </Text>
                      </Table.Td>
                      <Table.Td>
                        {channel ? (
                          <Group gap={6} wrap="nowrap">
                            <channel.icon size={18} />
                            <Text size="sm">{channel.label}</Text>
                          </Group>
                        ) : (
                          <Text size="sm" c="dimmed">
                            Added by your team
                          </Text>
                        )}
                      </Table.Td>
                      <Table.Td ta="right" style={{ fontVariantNumeric: 'tabular-nums' }}>
                        {c.conversations}
                      </Table.Td>
                      <Table.Td ta="right" style={{ fontVariantNumeric: 'tabular-nums' }}>
                        {c.appointments}
                      </Table.Td>
                      <Table.Td>
                        <Text size="sm">{friendlyDateTime(c.last_contact_at)}</Text>
                      </Table.Td>
                    </Table.Tr>
                  )
                })
              )}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      </Paper>
      {rows && (page > 0 || rows.length === PAGE_SIZE) && (
        <Group justify="center">
          <Button variant="default" disabled={page === 0} onClick={() => setPage((p) => p - 1)}>
            Previous
          </Button>
          <Text size="sm">Page {page + 1}</Text>
          <Button variant="default" disabled={rows.length < PAGE_SIZE} onClick={() => setPage((p) => p + 1)}>
            Next
          </Button>
        </Group>
      )}
    </Stack>
  )
}
