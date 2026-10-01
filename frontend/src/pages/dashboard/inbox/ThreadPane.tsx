import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { ActionIcon, Alert, Anchor, Badge, Button, Collapse, Group, Paper, Skeleton, Stack, Text, Textarea, Tooltip, UnstyledButton } from '@mantine/core'
import { notifications } from '@mantine/notifications'
import {
  IconArrowDown,
  IconArrowLeft,
  IconChevronDown,
  IconChevronUp,
  IconFlame,
  IconHeadset,
  IconLock,
  IconMail,
  IconPhone,
  IconRobot,
  IconSend,
  IconUserCheck,
} from '@tabler/icons-react'
import { apiFetch, ApiError } from '../../../api/client'
import type { InboxConversation, InboxMessage } from '../../../api/types'
import EmptyState from '../../../components/EmptyState'
import StatusBadge from '../../../components/StatusBadge'
import MessageBubble from './MessageBubble'
import QuickReplies from './QuickReplies'
import { channelInfo, clockTime, dayLabel, nameFromEmail } from './format'
import { usePolling } from './usePolling'
import { useStoredState } from './useStoredState'

const THREAD_LIMIT = 200

const newId = () =>
  typeof crypto !== 'undefined' && 'randomUUID' in crypto
    ? crypto.randomUUID()
    : `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 10)}`

// Re-render only when something visible changed (a new message, or a delivery status that moved).
const signature = (list: InboxMessage[]) => list.map((m) => `${m.id}:${m.delivery_status ?? ''}`).join('|')

interface Props {
  conversationId: string
  onBack?: () => void
  /** Called after anything that changes the conversation list (claim, release, reply, resolve). */
  onChanged: () => void
}

export default function ThreadPane({ conversationId, onBack, onChanged }: Props) {
  const [detail, setDetail] = useState<InboxConversation | null>(null)
  const [messages, setMessages] = useState<InboxMessage[] | null>(null)
  const [notFound, setNotFound] = useState(false)
  const [draft, setDraft] = useState('')
  const [pendingText, setPendingText] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [scrolledUp, setScrolledUp] = useState(false)
  const [leadOpen, setLeadOpen] = useStoredState('ng.inbox.leadSummaryOpen', true)
  const composer = useRef<HTMLTextAreaElement>(null)

  // The page renders this pane with key={conversationId}, so every conversation gets fresh state; `activeId` only guards
  // a response that arrives after the user has already moved on.
  const activeId = useRef(conversationId)
  const lastSignature = useRef('')
  const scroller = useRef<HTMLDivElement>(null)
  const stickToBottom = useRef(true)
  const lastReadFor = useRef<string | null>(null)

  const loadDetail = useCallback(async () => {
    const id = conversationId
    try {
      const d = await apiFetch<InboxConversation>(`/inbox/conversations/${id}`)
      if (activeId.current === id) setDetail(d)
    } catch (err) {
      if (err instanceof ApiError && err.status === 404 && activeId.current === id) setNotFound(true)
    }
  }, [conversationId])

  const loadMessages = useCallback(async () => {
    const id = conversationId
    try {
      const list = await apiFetch<InboxMessage[]>(`/inbox/conversations/${id}/messages?latest=true&limit=${THREAD_LIMIT}`)
      if (activeId.current !== id) return
      const sig = signature(list)
      if (sig !== lastSignature.current) {
        lastSignature.current = sig
        setMessages(list)
      }
    } catch {
      /* transient: the next poll retries; a 401 is handled globally */
    }
  }, [conversationId])

  usePolling(loadDetail, 5000)
  usePolling(loadMessages, 3000)

  // Follow the newest message — but only if the reader hasn't scrolled up to read history.
  useLayoutEffect(() => {
    const el = scroller.current
    if (el && stickToBottom.current) el.scrollTop = el.scrollHeight
  }, [messages, pendingText])

  const jumpToLatest = () => {
    const el = scroller.current
    if (!el) return
    stickToBottom.current = true
    setScrolledUp(false)
    el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' })
  }

  // Opening a conversation (and every new customer message while it is open) marks it read.
  const lastCustomerId = messages ? [...messages].reverse().find((m) => m.sender_type === 'customer')?.id ?? '' : null
  useEffect(() => {
    if (lastCustomerId === null || lastReadFor.current === lastCustomerId) return
    lastReadFor.current = lastCustomerId
    apiFetch(`/inbox/conversations/${conversationId}/read`, { method: 'POST' })
      .then(onChanged)
      .catch(() => undefined)
  }, [lastCustomerId, conversationId, onChanged])

  async function act(path: string, options: RequestInit, done?: string) {
    setBusy(true)
    try {
      await apiFetch(path, options)
      if (done) notifications.show({ message: done, color: 'green' })
      await loadDetail()
      onChanged()
    } catch (err) {
      notifications.show({ message: err instanceof ApiError ? err.message : 'Something went wrong.', color: 'red' })
    } finally {
      setBusy(false)
    }
  }

  const takeOver = () =>
    act(`/inbox/conversations/${conversationId}/takeover`, { method: 'POST' }, 'You are handling this conversation — the AI is paused.')
  const handBack = () =>
    act(`/inbox/conversations/${conversationId}/release`, { method: 'POST' }, 'Handed back to the AI.')
  const resolveHandoff = () =>
    detail?.open_handoff
      ? act(`/handoffs/${detail.open_handoff.id}`, { method: 'PATCH', body: JSON.stringify({ status: 'resolved' }) }, 'Handoff resolved — the AI is back in charge.')
      : undefined

  async function send(text: string) {
    const content = text.trim()
    if (!content || busy) return
    setBusy(true)
    setPendingText(content)
    stickToBottom.current = true
    try {
      // A fresh key per submit: the server treats a repeated key as the SAME reply (double-click safe).
      await apiFetch<InboxMessage>(`/inbox/conversations/${conversationId}/reply`, {
        method: 'POST',
        body: JSON.stringify({ content, client_msg_id: newId() }),
      })
      if (content === draft.trim()) setDraft('')
      await Promise.all([loadMessages(), loadDetail()])
      onChanged()
    } catch (err) {
      notifications.show({ message: err instanceof ApiError ? err.message : 'Could not send the reply.', color: 'red' })
      await loadDetail() // the window may just have closed
    } finally {
      setPendingText(null)
      setBusy(false)
    }
  }

  if (notFound) {
    return (
      <Paper p="xl" h="100%">
        <EmptyState title="Conversation not found" hint="It may belong to a different business, or no longer exist." />
      </Paper>
    )
  }

  const channel = detail ? channelInfo(detail.channel) : null
  const canReply = detail?.reply.can_reply ?? false
  const shown: InboxMessage[] = messages ?? []
  const withPending: InboxMessage[] = pendingText
    ? [
        ...shown,
        {
          id: 'pending',
          sender_type: 'staff',
          content: pendingText,
          created_at: new Date().toISOString(),
          delivery_status: 'pending',
          delivery_detail: null,
          sent_by_user_id: null,
          sent_by_email: 'You',
        },
      ]
    : shown

  return (
    <Paper p={0} h="100%" style={{ display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
      {/* header: who, where, how to reach them, and the one main action */}
      <Group p="md" gap="sm" wrap="nowrap" style={{ borderBottom: '1px solid var(--mantine-color-default-border)' }}>
        {onBack && (
          <ActionIcon onClick={onBack} aria-label="Back to conversations" hiddenFrom="md">
            <IconArrowLeft size={18} />
          </ActionIcon>
        )}
        {detail && channel ? (
          <>
            <div style={{ minWidth: 0, flex: 1 }}>
              <Text fw={600} truncate>
                {detail.customer_name}
              </Text>
              <Group gap={8} wrap="wrap" mt={2}>
                <Badge size="xs" color={channel.color}>
                  {channel.label}
                </Badge>
                {detail.customer_phone && (
                  <Anchor href={`tel:${detail.customer_phone}`} size="xs" c="dimmed" underline="hover" title="Call">
                    <Group gap={3} wrap="nowrap">
                      <IconPhone size={12} />
                      {detail.customer_phone}
                    </Group>
                  </Anchor>
                )}
                {detail.customer_email && (
                  <Anchor href={`mailto:${detail.customer_email}`} size="xs" c="dimmed" underline="hover" title="Send an email">
                    <Group gap={3} wrap="nowrap">
                      <IconMail size={12} />
                      {detail.customer_email}
                    </Group>
                  </Anchor>
                )}
                {detail.last_customer_message_at && (
                  <Text size="xs" c="dimmed">
                    Last wrote {dayLabel(detail.last_customer_message_at).toLowerCase()} {clockTime(detail.last_customer_message_at)}
                  </Text>
                )}
              </Group>
            </div>
            {detail.takeover.active ? (
              <Tooltip label="Give this conversation back to the AI right now">
                <Button size="xs" variant="default" leftSection={<IconRobot size={15} />} onClick={handBack} loading={busy}>
                  Hand back to AI
                </Button>
              </Tooltip>
            ) : (
              <Tooltip label="Pause the AI in this conversation so you can answer yourself">
                <Button size="xs" leftSection={<IconUserCheck size={15} />} onClick={takeOver} loading={busy}>
                  Take over
                </Button>
              </Tooltip>
            )}
          </>
        ) : (
          <Skeleton height={36} width="60%" />
        )}
      </Group>

      {/* one slim line: who is answering right now */}
      {detail && (
        <Group
          gap={8}
          px="md"
          py={6}
          wrap="nowrap"
          style={{
            borderBottom: '1px solid var(--mantine-color-default-border)',
            background: detail.takeover.active ? 'var(--mantine-color-blue-light)' : 'var(--mantine-color-default-hover)',
          }}
        >
          {detail.takeover.active ? <IconUserCheck size={15} /> : <IconRobot size={15} />}
          <Text size="xs" style={{ flex: 1 }}>
            {detail.takeover.active ? (
              <>
                <b>{nameFromEmail(detail.takeover_by_email)}</b> is answering — the AI is paused
                {detail.takeover.until && <> until {clockTime(detail.takeover.until)} (a reply extends it)</>}.
              </>
            ) : (
              <>
                <b>The AI is answering.</b> Type a reply below to step in — the AI pauses automatically.
              </>
            )}
          </Text>
        </Group>
      )}

      {/* escalation: needs a person */}
      {detail?.open_handoff && (
        <Alert color="orange" radius={0} icon={<IconHeadset size={16} />} py={8} title="The AI asked for a person">
          <Group justify="space-between" wrap="nowrap" gap="sm">
            <Text size="sm">{detail.open_handoff.reason}</Text>
            <Tooltip label="Close the handoff once the customer has been helped — the AI takes over again">
              <Button size="compact-xs" variant="light" color="teal" onClick={resolveHandoff} loading={busy} style={{ flexShrink: 0 }}>
                Mark resolved
              </Button>
            </Tooltip>
          </Group>
        </Alert>
      )}

      {/* automatic buying-intent triage, scored in the background (app/services/lead_service.py); collapsible, and the
          choice is remembered for every conversation */}
      {detail?.lead_summary && (
        <div
          style={{
            borderBottom: '1px solid var(--mantine-color-default-border)',
            background: detail.lead_signal === 'high' ? 'var(--mantine-color-green-light)' : 'var(--mantine-color-default-hover)',
          }}
        >
          <UnstyledButton
            onClick={() => setLeadOpen(!leadOpen)}
            aria-expanded={leadOpen}
            aria-controls="ng-lead-summary"
            w="100%"
            px="md"
            py={6}
          >
            <Group gap={8} wrap="nowrap">
              <IconFlame size={15} color={detail.lead_signal === 'high' ? 'var(--mantine-color-green-7)' : undefined} />
              <Text size="xs" fw={600}>
                Potential customer
              </Text>
              {detail.lead_signal && (
                <StatusBadge status={detail.lead_signal === 'high' ? 'high' : 'gray'} label={`${detail.lead_signal} intent`} size="xs" />
              )}
              {!leadOpen && (
                <Text size="xs" c="dimmed" truncate style={{ flex: 1 }}>
                  {detail.lead_summary}
                </Text>
              )}
              <Group gap={2} wrap="nowrap" ml="auto" style={{ flexShrink: 0 }}>
                <Text size="xs" c="dimmed">
                  {leadOpen ? 'Hide' : 'Show'}
                </Text>
                {leadOpen ? <IconChevronUp size={14} /> : <IconChevronDown size={14} />}
              </Group>
            </Group>
          </UnstyledButton>
          <Collapse expanded={leadOpen}>
            <Text id="ng-lead-summary" size="sm" px="md" pb="sm">
              {detail.lead_summary}
            </Text>
          </Collapse>
        </div>
      )}

      {/* messages */}
      <div style={{ position: 'relative', flex: 1, minHeight: 0, display: 'flex' }}>
        <div
          ref={scroller}
          tabIndex={0}
          role="log"
          aria-label="Messages"
          onScroll={(e) => {
            const el = e.currentTarget
            stickToBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80
            setScrolledUp(!stickToBottom.current)
          }}
          style={{ flex: 1, overflowY: 'auto', padding: 16, display: 'flex', flexDirection: 'column', gap: 10, minHeight: 0 }}
        >
          {messages === null ? (
            <Stack gap="sm">
              <Skeleton height={38} width="55%" />
              <Skeleton height={38} width="45%" ml="auto" />
              <Skeleton height={38} width="60%" />
            </Stack>
          ) : withPending.length === 0 ? (
            <EmptyState title="No messages yet" />
          ) : (
            <>
              {shown.length >= THREAD_LIMIT && (
                <Text size="xs" c="dimmed" ta="center">
                  Showing the latest {THREAD_LIMIT} messages
                </Text>
              )}
              {withPending.map((m, i) => {
                const newDay = i === 0 || dayLabel(withPending[i - 1].created_at) !== dayLabel(m.created_at)
                return (
                  <div key={m.id} style={{ display: 'contents' }}>
                    {newDay && (
                      <Text size="xs" c="dimmed" ta="center" my={4}>
                        {dayLabel(m.created_at)}
                      </Text>
                    )}
                    <MessageBubble message={m} onRetry={(text) => void send(text)} />
                  </div>
                )
              })}
            </>
          )}
        </div>
        {scrolledUp && (
          <Button
            size="compact-sm"
            radius="xl"
            variant="filled"
            leftSection={<IconArrowDown size={14} />}
            onClick={jumpToLatest}
            style={{ position: 'absolute', bottom: 12, left: '50%', transform: 'translateX(-50%)', boxShadow: 'var(--mantine-shadow-sm)' }}
          >
            Latest messages
          </Button>
        )}
      </div>

      {/* composer */}
      <div style={{ borderTop: '1px solid var(--mantine-color-default-border)', padding: 12 }}>
        {detail && !canReply ? (
          <Alert color="gray" icon={<IconLock size={16} />} title="You can't reply here right now">
            <Text size="sm">{detail.reply.reason}</Text>
          </Alert>
        ) : (
          <Group align="flex-end" gap="xs" wrap="nowrap">
            <QuickReplies
              draft={draft}
              disabled={!detail || busy}
              onPick={(text) => {
                setDraft(draft.trim() ? `${draft.trimEnd()} ${text}` : text)
                composer.current?.focus()
              }}
            />
            <Textarea
              ref={composer}
              style={{ flex: 1 }}
              autosize
              minRows={1}
              maxRows={6}
              placeholder={detail ? 'Write a reply…' : ''}
              aria-label="Reply"
              value={draft}
              disabled={!detail || busy}
              onChange={(e) => setDraft(e.currentTarget.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
                  e.preventDefault()
                  void send(draft)
                }
              }}
            />
            <Button leftSection={<IconSend size={16} />} onClick={() => void send(draft)} loading={busy} disabled={!draft.trim() || !detail}>
              Send
            </Button>
          </Group>
        )}
        {detail && canReply && (
          <Text size="xs" c="dimmed" mt={6}>
            Enter to send · Shift+Enter for a new line · Replying pauses the AI here for 2 hours
          </Text>
        )}
      </div>
    </Paper>
  )
}
