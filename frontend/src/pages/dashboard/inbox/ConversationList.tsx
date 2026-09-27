import { Box, Group, Indicator, Paper, ScrollArea, Skeleton, Stack, Text, ThemeIcon } from '@mantine/core'
import { IconMessages } from '@tabler/icons-react'
import type { InboxListItem } from '../../../api/types'
import EmptyState from '../../../components/EmptyState'
import StatusBadge from '../../../components/StatusBadge'
import { channelInfo, nameFromEmail, relativeTime, senderPrefix } from './format'

interface Props {
  items: InboxListItem[] | null
  selectedId: string | undefined
  onSelect: (id: string) => void
  emptyHint: string
}

function Row({ item, selected, onSelect }: { item: InboxListItem; selected: boolean; onSelect: () => void }) {
  const channel = channelInfo(item.channel)
  const Icon = channel.icon
  const failed = item.last_message_delivery_status === 'failed'
  return (
    <Box
      component="button"
      type="button"
      onClick={onSelect}
      aria-current={selected ? 'true' : undefined}
      style={{
        all: 'unset',
        boxSizing: 'border-box',
        display: 'block',
        width: '100%',
        cursor: 'pointer',
        padding: '12px 14px',
        borderBottom: '1px solid var(--mantine-color-default-border)',
        background: selected ? 'var(--mantine-primary-color-light)' : undefined,
      }}
    >
      <Group gap="sm" wrap="nowrap" align="flex-start">
        <Indicator disabled={!item.unread} size={9} offset={3} color="brand" processing={false}>
          <ThemeIcon variant="light" color={channel.color} size={36} radius="xl" aria-label={channel.label}>
            <Icon size={19} stroke={1.75} />
          </ThemeIcon>
        </Indicator>
        <Stack gap={3} style={{ minWidth: 0, flex: 1 }}>
          <Group justify="space-between" wrap="nowrap" gap={6}>
            <Text fw={item.unread ? 700 : 600} size="sm" truncate>
              {item.customer_name}
            </Text>
            <Text size="xs" c="dimmed" style={{ flexShrink: 0 }}>
              {relativeTime(item.last_message_at)}
            </Text>
          </Group>
          <Text size="sm" c={item.unread ? undefined : 'dimmed'} fw={item.unread ? 500 : 400} lineClamp={1}>
            {senderPrefix(item.last_message_sender)}
            {item.last_message_preview}
          </Text>
          <Group gap={6} mt={2}>
            {item.needs_reply && <StatusBadge status="waiting" label="Needs reply" size="xs" />}
            {item.open_handoff && <StatusBadge status="open" label="Handoff" size="xs" />}
            {item.takeover_active ? (
              <StatusBadge status="human" label={`${nameFromEmail(item.takeover_by_email)} handling`} size="xs" />
            ) : (
              <StatusBadge status="ai" label="AI" size="xs" />
            )}
            {failed && <StatusBadge status="failed" label="Not delivered" size="xs" />}
          </Group>
        </Stack>
      </Group>
    </Box>
  )
}

export default function ConversationList({ items, selectedId, onSelect, emptyHint }: Props) {
  return (
    <Paper p={0} style={{ overflow: 'hidden', height: '100%', display: 'flex', flexDirection: 'column' }}>
      <ScrollArea style={{ flex: 1 }} type="auto">
        {items === null ? (
          <Stack gap={0}>
            {Array.from({ length: 7 }).map((_, i) => (
              <Group key={i} p="md" gap="sm" wrap="nowrap">
                <Skeleton circle height={36} />
                <Stack gap={6} style={{ flex: 1 }}>
                  <Skeleton height={12} width="45%" />
                  <Skeleton height={10} width="80%" />
                </Stack>
              </Group>
            ))}
          </Stack>
        ) : items.length === 0 ? (
          <EmptyState
            icon={<IconMessages size={22} stroke={1.75} />}
            title="No conversations here"
            hint={emptyHint}
          />
        ) : (
          items.map((item) => (
            <Row key={item.id} item={item} selected={item.id === selectedId} onSelect={() => onSelect(item.id)} />
          ))
        )}
      </ScrollArea>
    </Paper>
  )
}
