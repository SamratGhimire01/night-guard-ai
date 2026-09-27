import { useEffect, useRef, useState } from 'react'
import { ActionIcon, Anchor, Button, Checkbox, Group, Modal, NumberInput, Paper, Stack, Table, Text, Textarea, TextInput, Tooltip } from '@mantine/core'
import { useForm } from '@mantine/form'
import { notifications } from '@mantine/notifications'
import { IconArchive, IconBook2, IconCheck, IconPlus, IconUpload, IconWorld } from '@tabler/icons-react'
import { useAuth } from '../../auth/AuthContext'
import { apiFetch, ApiError } from '../../api/client'
import type { KnowledgeDocumentRead, KnowledgeStatus } from '../../api/types'
import { EmptyRow } from '../../components/EmptyState'
import PageHeader from '../../components/PageHeader'
import RowActions from '../../components/RowActions'
import StatusBadge from '../../components/StatusBadge'
import TableSkeleton from '../../components/TableSkeleton'

export default function KnowledgePage() {
  const { role } = useAuth()
  const canWrite = role === 'owner' || role === 'admin'

  const [documents, setDocuments] = useState<KnowledgeDocumentRead[]>([])
  const [loading, setLoading] = useState(true)
  const [busyId, setBusyId] = useState<string | null>(null)
  const [uploading, setUploading] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const [createOpen, setCreateOpen] = useState(false)
  const [ingestOpen, setIngestOpen] = useState(false)
  const [ingesting, setIngesting] = useState(false)
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

  const createForm = useForm({
    initialValues: { title: '', content: '' },
    validate: {
      title: (v) => (v.trim() ? null : 'Title is required.'),
      content: (v) => (v.trim() ? null : 'Content is required.'),
    },
  })
  const editForm = useForm({ initialValues: { title: '', content: '' } })
  const ingestForm = useForm({
    initialValues: { url: '', crawl: false, max_pages: 5 },
    validate: { url: (v) => (v.trim() ? null : 'URL is required.') },
  })

  async function handleCreate(values: typeof createForm.values) {
    try {
      const created = await apiFetch<KnowledgeDocumentRead>('/knowledge', {
        method: 'POST',
        body: JSON.stringify(values),
      })
      setDocuments((prev) => [created, ...prev])
      notifications.show({ message: `"${created.title}" added — live now.`, color: 'green' })
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
      notifications.show({ message: `"${created.title}" uploaded — live now.`, color: 'green' })
    } catch (err) {
      notifications.show({ message: err instanceof ApiError ? err.message : 'Upload failed.', color: 'red' })
    } finally {
      setUploading(false)
    }
  }

  async function handleIngestUrl(values: typeof ingestForm.values) {
    setIngesting(true)
    try {
      const created = await apiFetch<KnowledgeDocumentRead[]>('/knowledge/ingest-url', {
        method: 'POST',
        body: JSON.stringify(values),
      })
      setDocuments((prev) => [...created, ...prev])
      notifications.show({
        message:
          created.length === 1
            ? `"${created[0].title}" fetched and added — live now.`
            : `${created.length} pages fetched and added — live now.`,
        color: 'green',
      })
      ingestForm.reset()
      setIngestOpen(false)
    } catch (err) {
      notifications.show({ message: err instanceof ApiError ? err.message : 'Fetching that URL failed.', color: 'red' })
    } finally {
      setIngesting(false)
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
      <PageHeader
        title="Knowledge Base"
        description="What your AI assistant knows. New documents go live immediately — archive one to stop it from being used."
        actions={
          canWrite && (
            <>
              <Button
                variant="default"
                leftSection={<IconUpload size={16} stroke={1.75} />}
                onClick={handleUploadClick}
                loading={uploading}
              >
                Upload file
              </Button>
              <input ref={fileInputRef} type="file" accept=".pdf,.txt" hidden onChange={handleFileChosen} />
              <Button
                variant="default"
                leftSection={<IconWorld size={16} stroke={1.75} />}
                onClick={() => setIngestOpen(true)}
              >
                From URL
              </Button>
              <Button leftSection={<IconPlus size={16} stroke={2} />} onClick={() => setCreateOpen(true)}>
                New document
              </Button>
            </>
          )
        }
      />

      <Paper p={0} style={{ overflow: 'hidden' }}>
        <Table.ScrollContainer minWidth={560}>
          <Table>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Title</Table.Th>
                <Table.Th>Status</Table.Th>
                <Table.Th visibleFrom="md">Source</Table.Th>
                <Table.Th visibleFrom="md">Version</Table.Th>
                <Table.Th />
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {loading && <TableSkeleton cols={5} />}
              {!loading && documents.length === 0 && (
                <EmptyRow
                  colSpan={5}
                  icon={<IconBook2 size={22} stroke={1.75} />}
                  title="No knowledge documents yet"
                  hint="Upload a PDF or write a document so the assistant can answer questions about your business."
                />
              )}
              {documents.map((doc) => (
                <Table.Tr key={doc.id}>
                  <Table.Td>
                    <Anchor component="button" type="button" fw={500} ta="left" onClick={() => openView(doc)}>
                      {doc.title}
                    </Anchor>
                  </Table.Td>
                  <Table.Td>
                    <StatusBadge status={doc.status} />
                  </Table.Td>
                  <Table.Td visibleFrom="md">{doc.source}</Table.Td>
                  <Table.Td visibleFrom="md">{doc.version}</Table.Td>
                  <Table.Td>
                    <Group gap={4} justify="flex-end" wrap="nowrap">
                      {canWrite ? (
                        <>
                          {doc.status !== 'approved' && (
                            <Tooltip label="Approve">
                              <ActionIcon
                                color="teal"
                                aria-label="Approve"
                                loading={busyId === doc.id}
                                onClick={() => setStatus(doc, 'approved')}
                              >
                                <IconCheck size={17} stroke={1.75} />
                              </ActionIcon>
                            </Tooltip>
                          )}
                          {doc.status !== 'archived' && (
                            <Tooltip label="Archive">
                              <ActionIcon
                                aria-label="Archive"
                                loading={busyId === doc.id}
                                onClick={() => setStatus(doc, 'archived')}
                              >
                                <IconArchive size={17} stroke={1.75} />
                              </ActionIcon>
                            </Tooltip>
                          )}
                          <RowActions canWrite onDelete={() => handleDelete(doc)} />
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
      </Paper>

      <Modal opened={createOpen} onClose={() => setCreateOpen(false)} title="New knowledge document" size="lg">
        <form onSubmit={createForm.onSubmit(handleCreate)}>
          <Stack gap="sm">
            <TextInput label="Title" withAsterisk {...createForm.getInputProps('title')} />
            <Textarea label="Content" withAsterisk autosize minRows={6} {...createForm.getInputProps('content')} />
            <Button type="submit">Create</Button>
          </Stack>
        </form>
      </Modal>

      <Modal opened={ingestOpen} onClose={() => setIngestOpen(false)} title="Add from a website URL" size="lg">
        <form onSubmit={ingestForm.onSubmit(handleIngestUrl)}>
          <Stack gap="sm">
            <Text c="dimmed" size="sm">
              Fetches the page, strips navigation/footer clutter, and adds the real content — live immediately, same
              as a manual entry or file upload.
            </Text>
            <TextInput
              label="Page URL"
              withAsterisk
              placeholder="https://example.com/faq"
              {...ingestForm.getInputProps('url')}
            />
            <Checkbox
              label="Also follow links on this page (same website only)"
              {...ingestForm.getInputProps('crawl', { type: 'checkbox' })}
            />
            {ingestForm.values.crawl && (
              <NumberInput
                label="Max pages"
                withAsterisk
                min={1}
                max={8}
                value={ingestForm.values.max_pages}
                onChange={(v) => ingestForm.setFieldValue('max_pages', v === '' ? 1 : Number(v))}
              />
            )}
            <Button type="submit" loading={ingesting}>
              Fetch and add
            </Button>
          </Stack>
        </form>
      </Modal>

      <Modal opened={viewing !== null} onClose={() => setViewing(null)} title={viewing?.title} size="lg">
        {viewing && (
          <Stack gap="sm">
            <StatusBadge status={viewing.status} w="fit-content" />
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
