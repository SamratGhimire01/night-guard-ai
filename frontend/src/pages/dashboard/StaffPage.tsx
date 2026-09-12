import { useEffect, useState } from 'react'
import {
  ActionIcon,
  Button,
  Center,
  Group,
  Loader,
  Modal,
  Stack,
  Table,
  Text,
  TextInput,
  Title,
  Tooltip,
} from '@mantine/core'
import { useForm } from '@mantine/form'
import { notifications } from '@mantine/notifications'
import { useAuth } from '../../auth/AuthContext'
import { apiFetch, ApiError } from '../../api/client'
import type { StaffRead, StaffWrite } from '../../api/types'

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
      <Group justify="space-between">
        <Title order={2}>Staff</Title>
        {canWrite ? (
          <Button onClick={openCreate}>Add staff member</Button>
        ) : (
          <Tooltip label="Owners and admins only">
            <Button disabled>Add staff member</Button>
          </Tooltip>
        )}
      </Group>

      <Table.ScrollContainer minWidth={500}>
        <Table verticalSpacing="sm">
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Name</Table.Th>
              <Table.Th>Role</Table.Th>
              <Table.Th />
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {loading && (
              <Table.Tr>
                <Table.Td colSpan={3}>
                  <Center py="md">
                    <Loader size="sm" />
                  </Center>
                </Table.Td>
              </Table.Tr>
            )}
            {!loading && staff.length === 0 && (
              <Table.Tr>
                <Table.Td colSpan={3}>
                  <Text c="dimmed" ta="center" py="md">
                    No staff members yet.
                  </Text>
                </Table.Td>
              </Table.Tr>
            )}
            {staff.map((member) => (
              <Table.Tr key={member.id}>
                <Table.Td>{member.name}</Table.Td>
                <Table.Td>{member.role}</Table.Td>
                <Table.Td>
                  <Group gap={4} justify="flex-end">
                    {canWrite ? (
                      <>
                        <ActionIcon variant="subtle" onClick={() => openEdit(member)} aria-label="Edit">
                          ✏️
                        </ActionIcon>
                        <ActionIcon
                          variant="subtle"
                          color="red"
                          onClick={() => handleDelete(member)}
                          aria-label="Delete"
                        >
                          🗑️
                        </ActionIcon>
                      </>
                    ) : (
                      <Tooltip label="Owners and admins only">
                        <Group gap={4}>
                          <ActionIcon variant="subtle" disabled aria-label="Edit (disabled)">
                            ✏️
                          </ActionIcon>
                          <ActionIcon variant="subtle" color="red" disabled aria-label="Delete (disabled)">
                            🗑️
                          </ActionIcon>
                        </Group>
                      </Tooltip>
                    )}
                  </Group>
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>

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
