import { useEffect, useState } from 'react'
import { Button, Modal, Paper, Stack, Table, TextInput, Tooltip } from '@mantine/core'
import { useForm } from '@mantine/form'
import { notifications } from '@mantine/notifications'
import { IconPlus, IconUsers } from '@tabler/icons-react'
import { useAuth } from '../../auth/AuthContext'
import { apiFetch, ApiError } from '../../api/client'
import type { StaffRead, StaffWrite } from '../../api/types'
import { EmptyRow } from '../../components/EmptyState'
import PageHeader from '../../components/PageHeader'
import RowActions from '../../components/RowActions'
import TableSkeleton from '../../components/TableSkeleton'

export default function StaffPage() {
  const { role } = useAuth()
  const canWrite = role === 'owner' || role === 'admin'

  const [staff, setStaff] = useState<StaffRead[]>([])
  const [loading, setLoading] = useState(true)
  const [editing, setEditing] = useState<StaffRead | null>(null)
  const [formOpen, setFormOpen] = useState(false)

  async function load() {
    try {
      setStaff(await apiFetch<StaffRead[]>('/staff'))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [])

  const form = useForm<StaffWrite>({
    initialValues: { name: '', role: '' },
    validate: {
      name: (v) => (v.trim() ? null : 'Name is required.'),
      role: (v) => (v.trim() ? null : 'Role is required.'),
    },
  })

  function openCreate() {
    setEditing(null)
    form.setValues({ name: '', role: '' })
    setFormOpen(true)
  }

  function openEdit(member: StaffRead) {
    setEditing(member)
    form.setValues({ name: member.name, role: member.role })
    setFormOpen(true)
  }

  async function handleSubmit(values: StaffWrite) {
    try {
      if (editing) {
        const updated = await apiFetch<StaffRead>(`/staff/${editing.id}`, {
          method: 'PATCH',
          body: JSON.stringify(values),
        })
        setStaff((prev) => prev.map((s) => (s.id === updated.id ? updated : s)))
        notifications.show({ message: `"${updated.name}" updated.`, color: 'green' })
      } else {
        const created = await apiFetch<StaffRead>('/staff', {
          method: 'POST',
          body: JSON.stringify(values),
        })
        setStaff((prev) => [...prev, created])
        notifications.show({ message: `"${created.name}" added.`, color: 'green' })
      }
      setFormOpen(false)
    } catch (err) {
      notifications.show({ message: err instanceof ApiError ? err.message : 'Save failed.', color: 'red' })
    }
  }

  async function handleDelete(member: StaffRead) {
    if (!window.confirm(`Delete "${member.name}"? This cannot be undone.`)) return
    try {
      await apiFetch(`/staff/${member.id}`, { method: 'DELETE' })
      setStaff((prev) => prev.filter((s) => s.id !== member.id))
      notifications.show({ message: `"${member.name}" deleted.`, color: 'green' })
    } catch (err) {
      notifications.show({ message: err instanceof ApiError ? err.message : 'Delete failed.', color: 'red' })
    }
  }

  return (
    <Stack gap="md">
      <PageHeader
        title="Staff"
        description="The people customers can be booked with."
        actions={
          canWrite ? (
            <Button leftSection={<IconPlus size={16} stroke={2} />} onClick={openCreate}>
              Add staff member
            </Button>
          ) : (
            <Tooltip label="Owners and admins only">
              <Button disabled leftSection={<IconPlus size={16} stroke={2} />}>
                Add staff member
              </Button>
            </Tooltip>
          )
        }
      />

      <Paper p={0} style={{ overflow: 'hidden' }}>
      <Table.ScrollContainer minWidth={500}>
        <Table>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Name</Table.Th>
              <Table.Th>Role</Table.Th>
              <Table.Th />
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {loading && <TableSkeleton cols={3} rows={3} />}
            {!loading && staff.length === 0 && (
              <EmptyRow
                colSpan={3}
                icon={<IconUsers size={22} stroke={1.75} />}
                title="No staff members yet"
                hint="Add the dentists and staff customers can book with."
              />
            )}
            {staff.map((member) => (
              <Table.Tr key={member.id}>
                <Table.Td>{member.name}</Table.Td>
                <Table.Td>{member.role}</Table.Td>
                <Table.Td>
                  <RowActions canWrite={canWrite} onEdit={() => openEdit(member)} onDelete={() => handleDelete(member)} />
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>
      </Paper>

      <Modal opened={formOpen} onClose={() => setFormOpen(false)} title={editing ? 'Edit staff member' : 'Add staff member'}>
        <form onSubmit={form.onSubmit(handleSubmit)}>
          <Stack gap="sm">
            <TextInput label="Name" withAsterisk {...form.getInputProps('name')} />
            <TextInput label="Role" placeholder="e.g. Dentist, Hygienist" withAsterisk {...form.getInputProps('role')} />
            <Button type="submit" mt="xs">
              {editing ? 'Save changes' : 'Add staff member'}
            </Button>
          </Stack>
        </form>
      </Modal>
    </Stack>
  )
}
