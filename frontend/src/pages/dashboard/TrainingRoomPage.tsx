import { useCallback, useEffect, useState } from 'react'
import {
  Badge,
  Button,
  Card,
  Center,
  Divider,
  Group,
  Loader,
  Stack,
  Text,
  Textarea,
  TextInput,
  Title,
} from '@mantine/core'
import { notifications } from '@mantine/notifications'
import { useAuth } from '../../auth/AuthContext'
import { apiFetch, ApiError } from '../../api/client'

interface KnowledgeChunkUsed {
  chunk_id: string
  document_id: string
  document_title: string
  content: string
  similarity: number
}

interface AskResponse {
  training_question_id: string
  question: string
  answer: string
  intent: string
  knowledge_chunks_used: KnowledgeChunkUsed[]
}

interface TrainingQuestion {
  id: string
  question: string
  answer: string
  intent: string
  is_correct: boolean | null
  corrected_answer: string | null
  feedback_at: string | null
  created_at: string
}

const PAGE_SIZE = 20

export default function TrainingRoomPage() {
  const { role } = useAuth()
  const allowed = role === 'owner' || role === 'admin'

  const [question, setQuestion] = useState('')
  const [asking, setAsking] = useState(false)
  const [current, setCurrent] = useState<AskResponse | null>(null)
  const [correcting, setCorrecting] = useState(false)
  const [correctedAnswer, setCorrectedAnswer] = useState('')

  const [qaQuestion, setQaQuestion] = useState('')
  const [qaAnswer, setQaAnswer] = useState('')
  const [saving, setSaving] = useState(false)

  const [history, setHistory] = useState<TrainingQuestion[] | null>(null)
  const [page, setPage] = useState(0)

  const loadHistory = useCallback(() => {
    if (!allowed) return
    setHistory(null)
    apiFetch<TrainingQuestion[]>(`/training/history?limit=${PAGE_SIZE}&offset=${page * PAGE_SIZE}`).then(setHistory)
  }, [allowed, page])

  useEffect(() => {
    loadHistory()
  }, [loadHistory])

  if (!allowed) {
    return (
      <Stack gap="md">
        <Title order={2}>AI Training Room</Title>
        <Text c="dimmed">This section is for owners and admins only.</Text>
      </Stack>
    )
  }

  async function handleAsk() {
    if (!question.trim()) return
    setAsking(true)
    setCurrent(null)
    setCorrecting(false)
    try {
      const result = await apiFetch<AskResponse>('/training/ask', {
        method: 'POST',
        body: JSON.stringify({ question }),
      })
      setCurrent(result)
    } catch (err) {
      notifications.show({ message: err instanceof ApiError ? err.message : 'Ask failed.', color: 'red' })
    } finally {
      setAsking(false)
    }
  }

  async function markFeedback(isCorrect: boolean, correctedText?: string) {
    if (!current) return
    try {
      await apiFetch('/training/feedback', {
        method: 'POST',
        body: JSON.stringify({
          training_question_id: current.training_question_id,
          is_correct: isCorrect,
          corrected_answer: isCorrect ? null : correctedText,
        }),
      })
      notifications.show({ message: isCorrect ? 'Marked correct.' : 'Correction submitted.', color: 'green' })
      setCurrent(null)
      setCorrecting(false)
      setQuestion('')
      loadHistory()
    } catch (err) {
      notifications.show({ message: err instanceof ApiError ? err.message : 'Feedback failed.', color: 'red' })
    }
  }

  async function handleSaveQA() {
    setSaving(true)
    try {
      await apiFetch('/training/qa', { method: 'POST', body: JSON.stringify({ question: qaQuestion, answer: qaAnswer }) })
      notifications.show({ message: 'Saved. The AI will use this answer straight away.', color: 'green' })
      setQaQuestion('')
      setQaAnswer('')
    } catch (err) {
      notifications.show({ message: err instanceof ApiError ? err.message : 'Save failed.', color: 'red' })
    } finally {
      setSaving(false)
    }
  }

  return (
    <Stack gap="lg">
      <Title order={2}>AI Training Room</Title>
      <Text c="dimmed" size="sm">
        Ask a real test question the way a customer would. See the exact answer the AI would give and which
        knowledge chunks it used, then mark it correct or submit a correction.
      </Text>

      <Card withBorder radius="md" p="md">
        <Group align="flex-end" gap="sm">
          <TextInput
            label="Test question"
            placeholder="e.g. Do you offer teeth whitening?"
            style={{ flex: 1 }}
            value={question}
            onChange={(e) => setQuestion(e.currentTarget.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleAsk()}
          />
          <Button onClick={handleAsk} loading={asking} disabled={!question.trim()}>
            Ask
          </Button>
        </Group>

        {current && (
          <Stack gap="sm" mt="md">
            <Divider />
            <Group gap="xs">
              <Text fw={600} size="sm">
                Answer
              </Text>
              <Badge variant="light">{current.intent}</Badge>
            </Group>
            <Text>{current.answer}</Text>

            <Text fw={600} size="sm" mt="xs">
              Knowledge chunks used ({current.knowledge_chunks_used.length})
            </Text>
            {current.knowledge_chunks_used.length === 0 ? (
              <Text size="sm" c="dimmed">
                No knowledge chunks were used for this answer.
              </Text>
            ) : (
              current.knowledge_chunks_used.map((chunk) => (
                <Card key={chunk.chunk_id} withBorder p="xs" radius="sm">
                  <Group justify="space-between">
                    <Text size="xs" fw={600}>
                      {chunk.document_title}
                    </Text>
                    <Text size="xs" c="dimmed">
                      similarity {chunk.similarity.toFixed(3)}
                    </Text>
                  </Group>
                  <Text size="xs" c="dimmed" mt={4} lineClamp={3}>
                    {chunk.content}
                  </Text>
                </Card>
              ))
            )}

            {!correcting ? (
              <Group gap="sm" mt="xs">
                <Button color="green" variant="light" onClick={() => markFeedback(true)}>
                  Mark correct
                </Button>
                <Button color="red" variant="light" onClick={() => setCorrecting(true)}>
                  Mark incorrect
                </Button>
              </Group>
            ) : (
              <Stack gap="xs" mt="xs">
                <Textarea
                  label="Corrected answer"
                  withAsterisk
                  value={correctedAnswer}
                  onChange={(e) => setCorrectedAnswer(e.currentTarget.value)}
                />
                <Group gap="sm">
                  <Button
                    color="red"
                    disabled={!correctedAnswer.trim()}
                    onClick={() => {
                      markFeedback(false, correctedAnswer)
                      setCorrectedAnswer('')
                    }}
                  >
                    Submit correction
                  </Button>
                  <Button variant="default" onClick={() => setCorrecting(false)}>
                    Cancel
                  </Button>
                </Group>
              </Stack>
            )}
          </Stack>
        )}
      </Card>

      <Card withBorder radius="md" p="md">
        <Stack gap="sm">
          <Title order={4}>Teach the AI directly</Title>
          <Text c="dimmed" size="sm">
            No test needed: write a question a customer might ask and the exact answer you want given. It becomes approved
            knowledge immediately (find it under Knowledge, source "training_room").
          </Text>
          <TextInput
            label="Question"
            placeholder="e.g. Do you offer teeth whitening?"
            value={qaQuestion}
            onChange={(e) => setQaQuestion(e.currentTarget.value)}
          />
          <Textarea
            label="Correct answer"
            autosize
            minRows={2}
            value={qaAnswer}
            onChange={(e) => setQaAnswer(e.currentTarget.value)}
          />
          <Group>
            <Button onClick={handleSaveQA} loading={saving} disabled={!qaQuestion.trim() || !qaAnswer.trim()}>
              Save Q&amp;A
            </Button>
          </Group>
        </Stack>
      </Card>

      <Stack gap="xs">
        <Title order={4}>History</Title>
        {history === null ? (
          <Center py="lg">
            <Loader />
          </Center>
        ) : history.length === 0 ? (
          <Text c="dimmed">No training questions asked yet.</Text>
        ) : (
          <>
            {history.map((h) => (
              <Card key={h.id} withBorder p="sm" radius="sm">
                <Group justify="space-between">
                  <Text fw={600} size="sm">
                    {h.question}
                  </Text>
                  {h.is_correct === null ? (
                    <Badge color="gray" variant="light">
                      No feedback yet
                    </Badge>
                  ) : h.is_correct ? (
                    <Badge color="green" variant="light">
                      Correct
                    </Badge>
                  ) : (
                    <Badge color="red" variant="light">
                      Corrected
                    </Badge>
                  )}
                </Group>
                <Text size="sm" c="dimmed" mt={4}>
                  {h.answer}
                </Text>
                {h.corrected_answer && (
                  <Text size="sm" c="teal" mt={4}>
                    Correction: {h.corrected_answer}
                  </Text>
                )}
                <Text size="xs" c="dimmed" mt={6}>
                  {new Date(h.created_at).toLocaleString()}
                </Text>
              </Card>
            ))}
            <Group justify="center" gap="sm">
              <Button variant="default" disabled={page === 0} onClick={() => setPage((p) => p - 1)}>
                Previous
              </Button>
              <Text size="sm" c="dimmed">
                Page {page + 1}
              </Text>
              <Button variant="default" disabled={history.length < PAGE_SIZE} onClick={() => setPage((p) => p + 1)}>
                Next
              </Button>
            </Group>
          </>
        )}
      </Stack>
    </Stack>
  )
}
