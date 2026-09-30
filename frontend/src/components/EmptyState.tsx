import type { ReactNode } from 'react'
import { Stack, Table, Text } from '@mantine/core'
import { IconInbox } from '@tabler/icons-react'

interface EmptyStateProps {
  title: string
  hint?: string
  icon?: ReactNode
  action?: ReactNode
}

export default function EmptyState({ title, hint, icon, action }: EmptyStateProps) {
  return (
    <Stack align="center" gap={8} py={36}>
      <span className="ng-empty-icon">{icon ?? <IconInbox size={24} stroke={1.75} />}</span>
      <Text fw={700} size="lg">
        {title}
      </Text>
      {hint && (
        <Text size="sm" c="dimmed" ta="center" maw={400}>
          {hint}
        </Text>
      )}
      {action}
    </Stack>
  )
}

/** The canonical placement: an empty state always lives INSIDE the table, never below it. */
export function EmptyRow({ colSpan, ...props }: EmptyStateProps & { colSpan: number }) {
  return (
    <Table.Tr>
      <Table.Td colSpan={colSpan}>
        <EmptyState {...props} />
      </Table.Td>
    </Table.Tr>
  )
}
