import { Button, Group, Paper, Text } from '@mantine/core'
import { IconAlertTriangle, IconCheck, IconClockHour4 } from '@tabler/icons-react'
import type { InboxMessage } from '../../../api/types'
import { clockTime, nameFromEmail } from './format'

interface Props {
  message: InboxMessage
  onRetry?: (content: string) => void
}

// A placeholder the system stored for a customer's non-text message (image, voice note, …).
const isPlaceholder = (m: InboxMessage) => m.sender_type === 'customer' && /^\[Customer .*\]$/.test(m.content)

function Delivery({ message, onRetry }: Props) {
  switch (message.delivery_status) {
    case 'failed':
      return (
        <Group gap={6} mt={4} wrap="wrap">
          <IconAlertTriangle size={14} color="var(--mantine-color-red-6)" />
          <Text size="xs" c="red" role="alert">
            Not delivered{message.delivery_detail ? ` — ${message.delivery_detail}` : ''}
          </Text>
          {onRetry && message.sender_type === 'staff' && (
            <Button size="compact-xs" variant="light" color="red" onClick={() => onRetry(message.content)}>
              Retry
            </Button>
          )}
        </Group>
      )
    case 'pending':
      return (
        <Group gap={4} mt={4}>
          <IconClockHour4 size={13} />
          <Text size="xs" c="dimmed">
            Sending…
          </Text>
        </Group>
      )
    case 'simulated':
      return (
        <Text size="xs" c="yellow.8" mt={4}>
          Simulated — no live channel token, nothing was sent
        </Text>
      )
    case 'suppressed':
      return (
        <Text size="xs" c="dimmed" mt={4}>
          Not sent — a staff member took over first
        </Text>
      )
    case 'sent':
      return (
        <Group gap={3} mt={4}>
          <IconCheck size={13} color="var(--mantine-color-teal-6)" />
          <Text size="xs" c="dimmed">
            Sent
          </Text>
        </Group>
      )
    default:
      return null
  }
}

export default function MessageBubble({ message, onRetry }: Props) {
  const mine = message.sender_type !== 'customer'
  const staff = message.sender_type === 'staff'
  const label = staff ? nameFromEmail(message.sent_by_email) : message.sender_type === 'agent' ? 'AI assistant' : null
  return (
    <div style={{ display: 'flex', justifyContent: mine ? 'flex-end' : 'flex-start' }}>
      <div style={{ maxWidth: 'min(78%, 560px)' }}>
        {label && (
          <Text size="xs" c="dimmed" ta={mine ? 'right' : 'left'} mb={2}>
            {label}
          </Text>
        )}
        <Paper
          px="sm"
          py={8}
          radius="lg"
          withBorder={!staff}
          bg={staff ? 'var(--mantine-primary-color-filled)' : mine ? 'var(--mantine-color-default-hover)' : undefined}
          c={staff ? 'white' : undefined}
        >
          <Text size="sm" style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word' }} fs={isPlaceholder(message) ? 'italic' : undefined}>
            {message.content}
          </Text>
        </Paper>
        <Group gap={8} justify={mine ? 'flex-end' : 'flex-start'} mt={2}>
          <Text size="xs" c="dimmed">
            {clockTime(message.created_at)}
          </Text>
        </Group>
        <div style={{ display: 'flex', justifyContent: mine ? 'flex-end' : 'flex-start' }}>
          <Delivery message={message} onRetry={onRetry} />
        </div>
      </div>
    </div>
  )
}
