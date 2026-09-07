import { useEffect, useState } from 'react'
import {
  ActionIcon,
  Badge,
  Button,
  Group,
  Modal,
  MultiSelect,
  NumberInput,
  Select,
  Stack,
  Table,
  Text,
  Textarea,
  TextInput,
  Title,
  Tooltip,
} from '@mantine/core'
import { useForm } from '@mantine/form'
import { notifications } from '@mantine/notifications'
import { useAuth } from '../../auth/AuthContext'
import { apiFetch, ApiError } from '../../api/client'
import type { BusinessRead, KnowledgeDocumentRead, ServiceRead, ServiceWrite, StaffRead } from '../../api/types'

export default function ServicesPage() {
  const { role } = useAuth()
  const canWrite = role === 'owner' || role === 'admin'

  const [services, setServices] = useState<ServiceRead[]>([])
  const [staff, setStaff] = useState<StaffRead[]>([])
  const [documents, setDocuments] = useState<KnowledgeDocumentRead[]>([])
  // The business's own real currency (e.g. "USD", "NPR") — read once here
  // rather than hardcoding "$" for every business regardless of what they
  // actually price in. Defaults to "USD" only until the real value loads.
  const [currency, setCurrency] = useState('USD')
  const [loading, setLoading] = useState(true)

  const [editing, setEditing] = useState<ServiceRead | null>(null)
  const [formOpen, setFormOpen] = useState(false)
  const [docsService, setDocsService] = useState<ServiceRead | null>(null)
  const [attachedDocs, setAttachedDocs] = useState<KnowledgeDocumentRead[]>([])
  const [docsLoading, setDocsLoading] = useState(false)

  async function loadAll() {
    try {
      const [s, st, docs] = await Promise.all([
        apiFetch<ServiceRead[]>('/services'),
        apiFetch<StaffRead[]>('/staff'),
        apiFetch<KnowledgeDocumentRead[]>('/knowledge'),
      ])
      setServices(s)
      setStaff(st)
      setDocuments(docs)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadAll()
    apiFetch<BusinessRead>('/business/me').then((b) => setCurrency(b.currency))
  }, [])

  const form = useForm<ServiceWrite>({
    initialValues: { name: '', description: '', price: '', duration_minutes: 30, staff_id: null },
  })

  function openCreate() {
    setEditing(null)
    form.setValues({ name: '', description: '', price: '', duration_minutes: 30, staff_id: null })
    setFormOpen(true)
  }

  function openEdit(service: ServiceRead) {
    setEditing(service)
    form.setValues({
      name: service.name,
      description: service.description ?? '',
      price: service.price,
      duration_minutes: service.duration_minutes,
      staff_id: service.staff_id,
    })
    setFormOpen(true)
  }

  async function handleSubmit(values: ServiceWrite) {
    const payload = { ...values, staff_id: values.staff_id || null, description: values.description || null }
    try {
      if (editing) {
        const updated = await apiFetch<ServiceRead>(`/services/${editing.id}`, {
          method: 'PATCH',
          body: JSON.stringify(payload),
        })
        setServices((prev) => prev.map((s) => (s.id === updated.id ? updated : s)))
        notifications.show({ message: `"${updated.name}" updated.`, color: 'green' })
      } else {
        const created = await apiFetch<ServiceRead>('/services', {
          method: 'POST',
          body: JSON.stringify(payload),
        })
        setServices((prev) => [...prev, created])
        notifications.show({ message: `"${created.name}" added.`, color: 'green' })
      }
      setFormOpen(false)
    } catch (err) {
      notifications.show({ message: err instanceof ApiError ? err.message : 'Save failed.', color: 'red' })
    }
  }

  async function handleDelete(service: ServiceRead) {
    if (!window.confirm(`Delete "${service.name}"? This cannot be undone.`)) return
    try {
      await apiFetch(`/services/${service.id}`, { method: 'DELETE' })
      setServices((prev) => prev.filter((s) => s.id !== service.id))
      notifications.show({ message: `"${service.name}" deleted.`, color: 'green' })
    } catch (err) {
      notifications.show({ message: err instanceof ApiError ? err.message : 'Delete failed.', color: 'red' })
    }
  }

  async function openDocs(service: ServiceRead) {
    setDocsService(service)
    setDocsLoading(true)
    try {
      const docs = await apiFetch<KnowledgeDocumentRead[]>(`/services/${service.id}/knowledge-documents`)
      setAttachedDocs(docs)
    } finally {
      setDocsLoading(false)
    }
  }

  async function attachDoc(documentId: string) {
    if (!docsService) return
    try {
      const doc = await apiFetch<KnowledgeDocumentRead>(`/services/${docsService.id}/knowledge-documents`, {
        method: 'POST',
        body: JSON.stringify({ knowledge_document_id: documentId }),
      })
      setAttachedDocs((prev) => [...prev, doc])
    } catch (err) {
      notifications.show({ message: err instanceof ApiError ? err.message : 'Attach failed.', color: 'red' })
    }
  }

  async function detachDoc(documentId: string) {
    if (!docsService) return
    try {
      await apiFetch(`/services/${docsService.id}/knowledge-documents/${documentId}`, { method: 'DELETE' })
      setAttachedDocs((prev) => prev.filter((d) => d.id !== documentId))
    } catch (err) {
      notifications.show({ message: err instanceof ApiError ? err.message : 'Detach failed.', color: 'red' })
    }
  }

  const staffName = (id: string | null) => staff.find((s) => s.id === id)?.name ?? '—'
  const attachedIds = new Set(attachedDocs.map((d) => d.id))
  const availableToAttach = documents.filter((d) => !attachedIds.has(d.id))

  return (
    <Stack gap="md">
      <Group justify="space-between">
        <Title order={2}>Services</Title>
        {canWrite ? (
          <Button onClick={openCreate}>Add service</Button>
        ) : (
          <Tooltip label="Owners and admins only">
            <Button disabled>Add service</Button>
          </Tooltip>
        )}
      </Group>

      <Table.ScrollContainer minWidth={700}>
        <Table verticalSpacing="sm">
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Name</Table.Th>
              <Table.Th>Price</Table.Th>
              <Table.Th>Duration</Table.Th>
              <Table.Th>Staff</Table.Th>
              <Table.Th>Documents</Table.Th>
              <Table.Th />
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {!loading && services.length === 0 && (
              <Table.Tr>
                <Table.Td colSpan={6}>
                  <Text c="dimmed" ta="center" py="md">
                    No services yet.
                  </Text>
                </Table.Td>
              </Table.Tr>
            )}
            {services.map((service) => (
              <Table.Tr key={service.id}>
                <Table.Td>{service.name}</Table.Td>
                <Table.Td>{currency} {service.price}</Table.Td>
                <Table.Td>{service.duration_minutes} min</Table.Td>
                <Table.Td>{staffName(service.staff_id)}</Table.Td>
                <Table.Td>
                  <Button variant="subtle" size="compact-sm" onClick={() => openDocs(service)}>
                    Manage
                  </Button>
                </Table.Td>
                <Table.Td>
                  <Group gap={4} justify="flex-end">
                    {canWrite ? (
                      <>
                        <ActionIcon variant="subtle" onClick={() => openEdit(service)} aria-label="Edit">
                          ✏️
                        </ActionIcon>
                        <ActionIcon
                          variant="subtle"
                          color="red"
                          onClick={() => handleDelete(service)}
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

      <Modal opened={formOpen} onClose={() => setFormOpen(false)} title={editing ? 'Edit service' : 'Add service'}>
        <form onSubmit={form.onSubmit(handleSubmit)}>
          <Stack gap="sm">
            <TextInput label="Name" required {...form.getInputProps('name')} />
            <Textarea label="Description" autosize minRows={2} {...form.getInputProps('description')} />
            <NumberInput
              label="Price"
              required
              min={0}
              decimalScale={2}
              fixedDecimalScale
              prefix={`${currency} `}
              value={form.values.price === '' ? '' : Number(form.values.price)}
              onChange={(v) => form.setFieldValue('price', String(v))}
            />
            <NumberInput
              label="Duration (minutes)"
              required
              min={1}
              {...form.getInputProps('duration_minutes')}
            />
            <Select
              label="Assigned staff"
              placeholder="Unassigned"
              clearable
              data={staff.map((s) => ({ value: s.id, label: `${s.name} (${s.role})` }))}
              value={form.values.staff_id}
              onChange={(v) => form.setFieldValue('staff_id', v)}
            />
            <Button type="submit" mt="xs">
              {editing ? 'Save changes' : 'Add service'}
            </Button>
          </Stack>
        </form>
      </Modal>

      <Modal
        opened={docsService !== null}
        onClose={() => setDocsService(null)}
        title={`Attached documents — ${docsService?.name ?? ''}`}
        size="lg"
      >
        <Stack gap="sm">
          <Text size="xs" c="dimmed">
            Purely organizational for this dashboard — attaching or detaching a document here does not
            change what the AI searches when answering customers (it still searches every approved document
            for the business).
          </Text>
          {docsLoading ? (
            <Text c="dimmed">Loading…</Text>
          ) : (
            <>
              {attachedDocs.length === 0 && (
                <Text c="dimmed" size="sm">
                  No documents attached yet.
                </Text>
              )}
              {attachedDocs.map((doc) => (
                <Group key={doc.id} justify="space-between">
                  <Group gap="xs">
                    <Text size="sm">{doc.title}</Text>
                    <Badge size="xs" variant="light">
                      {doc.status}
                    </Badge>
                  </Group>
                  {canWrite && (
                    <Button size="compact-xs" variant="subtle" color="red" onClick={() => detachDoc(doc.id)}>
                      Detach
                    </Button>
                  )}
                </Group>
              ))}
              {canWrite && availableToAttach.length > 0 && (
                <MultiSelect
                  mt="sm"
                  label="Attach a document"
                  placeholder="Choose a document to attach"
                  data={availableToAttach.map((d) => ({ value: d.id, label: `${d.title} (${d.status})` }))}
                  value={[]}
                  onChange={(values) => values.forEach(attachDoc)}
                />
              )}
            </>
          )}
        </Stack>
      </Modal>
    </Stack>
  )
}
