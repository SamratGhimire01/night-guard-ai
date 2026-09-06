import { useEffect, useRef, useState } from 'react'
import {
  ActionIcon,
  Badge,
  Button,
  Group,
  Modal,
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
import type { KnowledgeDocumentRead, KnowledgeStatus } from '../../api/types'

const STATUS_COLOR: Record<KnowledgeStatus, string> = {
  draft: 'gray',
  approved: 'green',
  archived: 'dark',
}

export default function KnowledgePage() {
  const { role } = useAuth()
  const canWrite = role === 'owner' || role === 'admin'

  const [documents, setDocuments] = useState<KnowledgeDocumentRead[]>([])
  const [loading, setLoading] = useState(true)
  const [busyId, setBusyId] = useState<string | null>(null)
  const [uploading, setUploading] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const [createOpen, setCreateOpen] = useState(false)
  const [viewing, setViewing] = useState<KnowledgeDocumentRead | null>(null)

  async function load() {
    try {
      setDocuments(await apiFetch<KnowledgeDocumentRead[]>('/knowledge'))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [])

  const createForm = useForm({ initialValues: { title: '', content: '' } })
  const editForm = useForm({ initialValues: { title: '', content: '' } })

  async function handleCreate(values: typeof createForm.values) {
    try {
      const created = await apiFetch<KnowledgeDocumentRead>('/knowledge', {
        method: 'POST',
        body: JSON.stringify(values),
      })
      setDocuments((prev) => [created, ...prev])
      notifications.show({ message: `"${created.title}" created as a draft.`, color: 'green' })
      createForm.reset()
      setCreateOpen(false)
    } catch (err) {
      notifications.show({ message: err instanceof ApiError ? err.message : 'Create failed.', color: 'red' })
    }
  }

  async function handleUploadClick() {
    fileInputRef.current?.click()
  }

  async function handleFileChosen(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (!file) return
    setUploading(true)
    try {
      const formData = new FormData()
      formData.append('file', file)
      const created = await apiFetch<KnowledgeDocumentRead>('/knowledge/upload', {
        method: 'POST',
        body: formData,
      })
      setDocuments((prev) => [created, ...prev])
      notifications.show({ message: `"${created.title}" uploaded as a draft.`, color: 'green' })
    } catch (err) {
      notifications.show({ message: err instanceof ApiError ? err.message : 'Upload failed.', color: 'red' })
    } finally {
      setUploading(false)
    }
  }

  async function setStatus(doc: KnowledgeDocumentRead, status: KnowledgeStatus) {
    setBusyId(doc.id)
    try {
      const updated = await apiFetch<KnowledgeDocumentRead>(`/knowledge/${doc.id}`, {
        method: 'PATCH',
        body: JSON.stringify({ status }),
      })
      setDocuments((prev) => prev.map((d) => (d.id === updated.id ? updated : d)))
      notifications.show({
        message:
          status === 'approved'
            ? `"${updated.title}" approved — chunked and embedded for search.`
            : `"${updated.title}" archived.`,
        color: 'green',
      })
    } catch (err) {
      notifications.show({ message: err instanceof ApiError ? err.message : 'Update failed.', color: 'red' })
    } finally {
      setBusyId(null)
    }
  }

  async function handleDelete(doc: KnowledgeDocumentRead) {
    if (!window.confirm(`Delete "${doc.title}"? This cannot be undone.`)) return
    try {
      await apiFetch(`/knowledge/${doc.id}`, { method: 'DELETE' })
      setDocuments((prev) => prev.filter((d) => d.id !== doc.id))
      notifications.show({ message: `"${doc.title}" deleted.`, color: 'green' })
    } catch (err) {
      notifications.show({ message: err instanceof ApiError ? err.message : 'Delete failed.', color: 'red' })
    }
  }

  function openView(doc: KnowledgeDocumentRead) {
    setViewing(doc)
    editForm.setValues({ title: doc.title, content: doc.content })
  }

  async function handleSaveEdit() {
    if (!viewing) return
    try {
      const updated = await apiFetch<KnowledgeDocumentRead>(`/knowledge/${viewing.id}`, {
        method: 'PATCH',
        body: JSON.stringify(editForm.values),
      })
      setDocuments((prev) => prev.map((d) => (d.id === updated.id ? updated : d)))
      notifications.show({ message: 'Saved.', color: 'green' })
      setViewing(null)
    } catch (err) {
      notifications.show({ message: err instanceof ApiError ? err.message : 'Save failed.', color: 'red' })
    }
  }

  return (
    <Stack gap="md">
      <Group justify="space-between">
        <Title order={2}>Knowledge Base</Title>
        {canWrite && (
          <Group>
            <Button variant="default" onClick={handleUploadClick} loading={uploading}>
              Upload file
            </Button>
            <input
              ref={fileInputRef}
              type="file"
              accept=".pdf,.txt"
              hidden
              onChange={handleFileChosen}
            />
            <Button onClick={() => setCreateOpen(true)}>New document</Button>
          </Group>
        )}
      </Group>

      <Table.ScrollContainer minWidth={700}>
        <Table verticalSpacing="sm">
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Title</Table.Th>
              <Table.Th>Status</Table.Th>
              <Table.Th>Source</Table.Th>
              <Table.Th>Version</Table.Th>
              <Table.Th />
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {!loading && documents.length === 0 && (
              <Table.Tr>
                <Table.Td colSpan={5}>
                  <Text c="dimmed" ta="center" py="md">
                    No knowledge documents yet.
                  </Text>
                </Table.Td>
              </Table.Tr>
            )}
            {documents.map((doc) => (
              <Table.Tr key={doc.id}>
                <Table.Td>
                  <Text component="button" onClick={() => openView(doc)} style={{ all: 'unset', cursor: 'pointer', textDecoration: 'underline' }}>
                    {doc.title}
                  </Text>
                </Table.Td>
                <Table.Td>
                  <Badge color={STATUS_COLOR[doc.status]} variant="light" tt="capitalize">
                    {doc.status}
                  </Badge>
                </Table.Td>
                <Table.Td>{doc.source}</Table.Td>
                <Table.Td>{doc.version}</Table.Td>
                <Table.Td>
                  <Group gap={4} justify="flex-end">
                    {canWrite ? (
                      <>
                        {doc.status !== 'approved' && (
                          <Button
                            size="compact-xs"
                            variant="light"
                            color="green"
                            loading={busyId === doc.id}
                            onClick={() => setStatus(doc, 'approved')}
                          >
                            Approve
                          </Button>
                        )}
                        {doc.status !== 'archived' && (
                          <Button
                            size="compact-xs"
                            variant="light"
                            loading={busyId === doc.id}
                            onClick={() => setStatus(doc, 'archived')}
                          >
                            Archive
                          </Button>
                        )}
                        <ActionIcon variant="subtle" color="red" onClick={() => handleDelete(doc)} aria-label="Delete">
                          🗑️
                        </ActionIcon>
                      </>
                    ) : (
                      <Tooltip label="Owners and admins only">
                        <Text size="xs" c="dimmed">
                          Read-only
                        </Text>
                      </Tooltip>
                    )}
                  </Group>
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>

      <Modal opened={createOpen} onClose={() => setCreateOpen(false)} title="New knowledge document" size="lg">
        <form onSubmit={createForm.onSubmit(handleCreate)}>
          <Stack gap="sm">
            <TextInput label="Title" required {...createForm.getInputProps('title')} />
            <Textarea label="Content" required autosize minRows={6} {...createForm.getInputProps('content')} />
            <Button type="submit">Create as draft</Button>
          </Stack>
        </form>
      </Modal>

      <Modal opened={viewing !== null} onClose={() => setViewing(null)} title={viewing?.title} size="lg">
        {viewing && (
          <Stack gap="sm">
            <Badge color={STATUS_COLOR[viewing.status]} variant="light" tt="capitalize" w="fit-content">
              {viewing.status}
            </Badge>
            {canWrite ? (
              <>
                <TextInput label="Title" {...editForm.getInputProps('title')} />
                <Textarea label="Content" autosize minRows={8} {...editForm.getInputProps('content')} />
                <Button onClick={handleSaveEdit}>Save changes</Button>
              </>
            ) : (
              <Text style={{ whiteSpace: 'pre-wrap' }}>{viewing.content}</Text>
            )}
          </Stack>
        )}
      </Modal>
    </Stack>
  )
}
