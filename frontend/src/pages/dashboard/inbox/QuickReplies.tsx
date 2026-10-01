import { ActionIcon, Button, Menu, Text, Tooltip } from '@mantine/core'
import { IconBolt, IconDeviceFloppy, IconX } from '@tabler/icons-react'
import { useStoredState } from './useStoredState'

const DEFAULTS = [
  'Thank you for your message! Let me check that for you.',
  'Could you share the date and time that works best for you?',
  'Your booking is confirmed. We look forward to seeing you!',
  'Sorry for the wait — I am looking into this now.',
]

interface Props {
  /** The composer's current text, offered for saving as a new quick reply. */
  draft: string
  onPick: (text: string) => void
  disabled?: boolean
}

/** Saved answers staff send often, one click to drop into the reply box (kept in this browser). */
export default function QuickReplies({ draft, onPick, disabled }: Props) {
  const [replies, setReplies] = useStoredState<string[]>('ng.inbox.quickReplies', DEFAULTS)
  const canSave = draft.trim().length > 0 && !replies.includes(draft.trim())

  return (
    <Menu position="top-start" width={340} withinPortal shadow="md">
      <Menu.Target>
        <Tooltip label="Quick replies: insert a saved answer">
          <Button variant="default" size="sm" px="xs" disabled={disabled} aria-label="Quick replies">
            <IconBolt size={17} />
          </Button>
        </Tooltip>
      </Menu.Target>
      <Menu.Dropdown>
        <Menu.Label>Quick replies</Menu.Label>
        {replies.length === 0 && (
          <Text size="xs" c="dimmed" px="sm" py={6}>
            None saved yet. Type a reply, then save it here.
          </Text>
        )}
        {replies.map((text) => (
          <Menu.Item
            key={text}
            onClick={() => onPick(text)}
            rightSection={
              <ActionIcon
                component="span"
                size="sm"
                variant="subtle"
                color="gray"
                aria-label="Delete quick reply"
                onClick={(e) => {
                  e.stopPropagation()
                  setReplies(replies.filter((r) => r !== text))
                }}
              >
                <IconX size={14} />
              </ActionIcon>
            }
          >
            <Text size="sm" lineClamp={2}>
              {text}
            </Text>
          </Menu.Item>
        ))}
        <Menu.Divider />
        <Menu.Item
          leftSection={<IconDeviceFloppy size={15} />}
          disabled={!canSave}
          onClick={() => setReplies([...replies, draft.trim()])}
        >
          Save what I typed as a quick reply
        </Menu.Item>
      </Menu.Dropdown>
    </Menu>
  )
}
