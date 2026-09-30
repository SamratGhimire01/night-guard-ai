import { useCallback, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { Group, Paper, SegmentedControl, Select, Stack, TextInput } from '@mantine/core'
import { useDebouncedValue, useMediaQuery } from '@mantine/hooks'
import { IconInbox, IconSearch } from '@tabler/icons-react'
import { apiFetch } from '../../api/client'
import type { InboxListItem } from '../../api/types'
import EmptyState from '../../components/EmptyState'
import PageHeader from '../../components/PageHeader'
import ConversationList from './inbox/ConversationList'
import ThreadPane from './inbox/ThreadPane'
import { usePolling } from './inbox/usePolling'

type Tab = 'needs_reply' | 'handoffs' | 'leads' | 'all'

const EMPTY_HINT: Record<Tab, string> = {
  needs_reply: 'Nobody is waiting for a person right now. Conversations the AI escalates, or that you take over, show up here when the customer writes.',
  handoffs: 'No conversation has an open handoff.',
  leads: "No high-intent leads right now. The AI scores conversations in the background as customers show real buying signals (price, availability, wanting to book) — check back shortly.",
  all: 'When customers message you on WhatsApp, Messenger, Instagram or your website, the conversations appear here.',
}

export default function InboxPage() {
  const { conversationId } = useParams()
  const navigate = useNavigate()
  const compact = useMediaQuery('(max-width: 62em)') // below Mantine "md": one pane at a time

  const [tab, setTab] = useState<Tab>('needs_reply')
  const [channel, setChannel] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [debouncedSearch] = useDebouncedValue(search, 300)
  const [items, setItems] = useState<InboxListItem[] | null>(null)

  const loadList = useCallback(async () => {
    const params = new URLSearchParams({ tab, limit: '100' })
    if (channel) params.set('channel', channel)
    if (debouncedSearch.trim()) params.set('q', debouncedSearch.trim())
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
              value={tab}
              onChange={(v) => {
                setItems(null)
                setTab(v as Tab)
              }}
              data={[
                { value: 'needs_reply', label: 'Needs reply' },
                { value: 'handoffs', label: 'Handoffs' },
                { value: 'leads', label: 'Leads' },
                { value: 'all', label: 'All' },
              ]}
            />
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
