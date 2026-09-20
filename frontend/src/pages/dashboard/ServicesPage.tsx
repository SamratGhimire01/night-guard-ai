import { useEffect, useState } from 'react'
import {
  Badge,
  Button,
  Group,
  Modal,
  MultiSelect,
  NumberInput,
  Paper,
  Select,
  Stack,
  Switch,
  Table,
  Text,
  TextInput,
  Textarea,
  Tooltip,
} from '@mantine/core'
import { useForm } from '@mantine/form'
import { notifications } from '@mantine/notifications'
import { IconDental, IconPlus } from '@tabler/icons-react'
import { useAuth } from '../../auth/AuthContext'
import { apiFetch, ApiError } from '../../api/client'
import type { BusinessRead, KnowledgeDocumentRead, ServiceRead, ServiceWrite, StaffRead } from '../../api/types'
import { EmptyRow } from '../../components/EmptyState'
import PageHeader from '../../components/PageHeader'
import RowActions from '../../components/RowActions'
import TableSkeleton from '../../components/TableSkeleton'

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
    initialValues: {
      name: '',
      description: '',
      price: '',
      duration_minutes: 30,
      staff_id: null,
      deposit_enabled: false,
      deposit_percentage: null,
    },
    // withAsterisk (visual only, no native "required" attribute) + this
    // validate config replaces the browser's own "Please fill out this
    // field" tooltip with a real styled inline Mantine error.
    validate: {
      name: (v) => (v.trim() ? null : 'Name is required.'),
      price: (v) => (v !== '' && Number(v) >= 0 ? null : 'Enter a valid, non-negative price.'),
      duration_minutes: (v) => (v && Number(v) > 0 ? null : 'Duration must be a positive number of minutes.'),
      deposit_percentage: (v, values) =>
        values.deposit_enabled && !(Number(v) >= 1 && Number(v) <= 100)
          ? 'Enter a percentage from 1 to 100.'
          : null,
    },
  })

  function openCreate() {
    setEditing(null)
    form.setValues({
      name: '',
      description: '',
      price: '',
      duration_minutes: 30,
      staff_id: null,
      deposit_enabled: false,
      deposit_percentage: null,
    })
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
      deposit_enabled: service.deposit_enabled,
      deposit_percentage: service.deposit_percentage,
    })
    setFormOpen(true)
  }

  async function handleSubmit(values: ServiceWrite) {
    const payload = {
      ...values,
      staff_id: values.staff_id || null,
      description: values.description || null,
      deposit_percentage: values.deposit_enabled ? values.deposit_percentage : null,
    }
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
      <PageHeader
        title="Services"
        description="What customers can book, with price, duration and deposit."
        actions={
          canWrite ? (
            <Button leftSection={<IconPlus size={16} stroke={2} />} onClick={openCreate}>
              Add service
            </Button>
          ) : (
            <Tooltip label="Owners and admins only">
              <Button disabled leftSection={<IconPlus size={16} stroke={2} />}>
                Add service
              </Button>
            </Tooltip>
          )
        }
      />

      <Paper p={0} style={{ overflow: 'hidden' }}>
      <Table.ScrollContainer minWidth={560}>
        <Table>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Name</Table.Th>
              <Table.Th>Price</Table.Th>
              <Table.Th>Duration</Table.Th>
              <Table.Th>Deposit</Table.Th>
              <Table.Th visibleFrom="md">Staff</Table.Th>
              <Table.Th>Documents</Table.Th>
              <Table.Th />
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {loading && <TableSkeleton cols={7} />}
            {!loading && services.length === 0 && (
              <EmptyRow
                colSpan={7}
                icon={<IconDental size={22} stroke={1.75} />}
                title="No services yet"
                hint="Add the treatments customers can book."
              />
            )}
            {services.map((service) => (
              <Table.Tr key={service.id}>
                <Table.Td>{service.name}</Table.Td>
                <Table.Td style={{ whiteSpace: 'nowrap' }}>
                  {currency} {service.price}
                </Table.Td>
                <Table.Td style={{ whiteSpace: 'nowrap' }}>{service.duration_minutes} min</Table.Td>
                <Table.Td>
                  {service.deposit_enabled ? (
                    <Badge color="gray" variant="light">
                      {service.deposit_percentage}%
                    </Badge>
                  ) : (
                    <Text c="dimmed" size="sm" style={{ whiteSpace: 'nowrap' }}>
                      Pay at clinic
                    </Text>
                  )}
                </Table.Td>
                <Table.Td visibleFrom="md">{staffName(service.staff_id)}</Table.Td>
                <Table.Td>
                  <Button variant="subtle" size="compact-sm" onClick={() => openDocs(service)}>
                    Manage
                  </Button>
                </Table.Td>
                <Table.Td>
                  <RowActions canWrite={canWrite} onEdit={() => openEdit(service)} onDelete={() => handleDelete(service)} />
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>
      </Paper>

      <Modal opened={formOpen} onClose={() => setFormOpen(false)} title={editing ? 'Edit service' : 'Add service'}>
        <form onSubmit={form.onSubmit(handleSubmit)}>
          <Stack gap="sm">
            <TextInput label="Name" withAsterisk {...form.getInputProps('name')} />
            <Textarea label="Description" autosize minRows={2} {...form.getInputProps('description')} />
            <NumberInput
              label="Price"
              withAsterisk
              min={0}
              decimalScale={2}
              fixedDecimalScale
              prefix={`${currency} `}
              value={form.values.price === '' ? '' : Number(form.values.price)}
              onChange={(v) => form.setFieldValue('price', String(v))}
              error={form.errors.price}
            />
            <NumberInput
              label="Duration (minutes)"
              withAsterisk
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
            <Switch
              label="Require an online deposit to confirm booking"
              description="When off, the customer pays in person at the clinic and no payment link is generated."
              checked={form.values.deposit_enabled}
              onChange={(e) => form.setFieldValue('deposit_enabled', e.currentTarget.checked)}
            />
            {form.values.deposit_enabled && (
              <NumberInput
                label="Deposit percentage"
                withAsterisk
                min={1}
                max={100}
                suffix="%"
                value={form.values.deposit_percentage ?? ''}
                onChange={(v) => form.setFieldValue('deposit_percentage', v === '' ? null : Number(v))}
                error={form.errors.deposit_percentage}
              />
            )}
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
