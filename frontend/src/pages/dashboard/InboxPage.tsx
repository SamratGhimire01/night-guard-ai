import { useCallback, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { Badge, Group, Paper, SegmentedControl, Select, Stack, Text, TextInput } from '@mantine/core'
import { useDebouncedValue, useMediaQuery } from '@mantine/hooks'
import { IconInbox, IconSearch } from '@tabler/icons-react'
import { apiFetch } from '../../api/client'
import type { InboxListItem, InboxSummary } from '../../api/types'
import EmptyState from '../../components/EmptyState'
import PageHeader from '../../components/PageHeader'
import ConversationList from './inbox/ConversationList'
import ThreadPane from './inbox/ThreadPane'
import { usePolling } from './inbox/usePolling'

type Tab = 'needs_reply' | 'handoffs' | 'leads' | 'all'

const EMPTY_HINT: Record<Tab, string> = {
  needs_reply: 'Nobody is waiting for a person right now. Conversations the AI escalates, or that you take over, show up here when the customer writes.',
  handoffs: 'No conversation has an open handoff.',
  leads: "No high-intent leads right now. Customers who ask about prices, availability or booking show up here, so you can follow up while they're interested.",
  all: 'When customers message you on WhatsApp, Messenger, Instagram or your website, the conversations appear here.',
}

// One line under the tabs, so anyone can tell what they are looking at without learning the jargon.
const TAB_HINT: Record<Tab, string> = {
  needs_reply: 'Customers waiting for an answer from a person. Start here.',
  handoffs: 'Conversations the AI passed to your team. Mark resolved when done.',
  leads: 'People who look ready to book or buy. A good moment to follow up.',
  all: 'Every conversation, newest first. The AI answers most of them for you.',
}

const TABS: { value: Tab; label: string; count?: keyof InboxSummary }[] = [
  { value: 'needs_reply', label: 'Needs reply', count: 'needs_reply' },
  { value: 'handoffs', label: 'Handoffs', count: 'handoffs' },
  { value: 'leads', label: 'Leads', count: 'leads' },
  { value: 'all', label: 'All' },
]

export default function InboxPage() {
  const { conversationId } = useParams()
  const navigate = useNavigate()
  const compact = useMediaQuery('(max-width: 62em)') // below Mantine "md": one pane at a time

  const [tab, setTab] = useState<Tab>('needs_reply')
  const [channel, setChannel] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [debouncedSearch] = useDebouncedValue(search, 300)
  const [items, setItems] = useState<InboxListItem[] | null>(null)
  const [summary, setSummary] = useState<InboxSummary | null>(null)

  const loadList = useCallback(async () => {
    const params = new URLSearchParams({ tab, limit: '100' })
    if (channel) params.set('channel', channel)
    if (debouncedSearch.trim()) params.set('q', debouncedSearch.trim())
    apiFetch<InboxSummary>('/inbox/summary')
      .then(setSummary)
      .catch(() => undefined) // the counts are a convenience; keep the last ones
    try {
      setItems(await apiFetch<InboxListItem[]>(`/inbox/conversations?${params}`))
    } catch {
      /* transient: the next poll retries; a 401 is handled globally */
    }
  }, [tab, channel, debouncedSearch])

  // Re-runs (immediately) whenever a filter changes, then every 10s while the tab is visible.
  usePolling(loadList, 10000, true, `${tab}|${channel}|${debouncedSearch}`)

  const select = (id: string) => navigate(`/dashboard/inbox/${id}`)
  const showList = !compact || !conversationId
  const showThread = !compact || !!conversationId

  return (
    <Stack gap="md">
      <PageHeader
        title="Inbox"
        description="Every customer conversation across WhatsApp, Messenger, Instagram and your website — reply from here and the customer gets it on their own channel."
      />

      <div style={{ display: 'flex', gap: 16, height: 'calc(100svh - 230px)', minHeight: 460 }}>
        {showList && (
          <Stack gap="sm" style={{ width: compact ? '100%' : 380, flexShrink: 0, minHeight: 0 }}>
            <SegmentedControl
              fullWidth
              size="xs"
              value={tab}
              onChange={(v) => {
                setItems(null)
                setTab(v as Tab)
              }}
              data={TABS.map((t) => {
                const n = t.count && summary ? summary[t.count] : 0
                return {
                  value: t.value,
                  label: (
                    <Group gap={4} wrap="nowrap" justify="center">
                      <span>{t.label}</span>
                      {n > 0 &&
                        (t.value === 'needs_reply' ? (
                          <Badge size="xs" circle={n < 10} color="orange" variant="filled" style={{ flexShrink: 0 }}>
                            {n > 99 ? '99+' : n}
                          </Badge>
                        ) : (
                          <Text span size="xs" c="dimmed" fw={700}>
                            {n > 99 ? '99+' : n}
                          </Text>
                        ))}
                    </Group>
                  ),
                }
              })}
            />
            <Text size="xs" c="dimmed" mt={-4}>
              {TAB_HINT[tab]}
            </Text>
            <Group gap="xs" wrap="nowrap">
              <TextInput
                style={{ flex: 1 }}
                placeholder="Search customers"
                aria-label="Search customers"
                leftSection={<IconSearch size={15} />}
                value={search}
                onChange={(e) => setSearch(e.currentTarget.value)}
              />
              <Select
                w={160}
                placeholder="All channels"
                aria-label="Filter by channel"
                clearable
                value={channel}
                onChange={setChannel}
                data={[
                  { value: 'whatsapp', label: 'WhatsApp' },
                  { value: 'messenger', label: 'Messenger' },
                  { value: 'instagram', label: 'Instagram' },
                  { value: 'website', label: 'Website' },
                ]}
              />
            </Group>
            <div style={{ flex: 1, minHeight: 0 }}>
              <ConversationList items={items} selectedId={conversationId} onSelect={select} emptyHint={EMPTY_HINT[tab]} />
            </div>
          </Stack>
        )}

        {showThread && (
          <div style={{ flex: 1, minWidth: 0 }}>
            {conversationId ? (
              <ThreadPane
                key={conversationId}
                conversationId={conversationId}
                onBack={compact ? () => navigate('/dashboard/inbox') : undefined}
                onChanged={loadList}
              />
            ) : (
              <Paper h="100%" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                <EmptyState
                  icon={<IconInbox size={22} stroke={1.75} />}
                  title="Select a conversation"
                  hint="Pick one on the left to read it and reply."
                />
              </Paper>
            )}
          </div>
        )}
      </div>
    </Stack>
  )
}
