import type { ReactNode } from 'react'
import { Stack, Table, Text, ThemeIcon } from '@mantine/core'
import { IconInbox } from '@tabler/icons-react'

interface EmptyStateProps {
  title: string
  hint?: string
  icon?: ReactNode
  action?: ReactNode
}

export default function EmptyState({ title, hint, icon, action }: EmptyStateProps) {
  return (
    <Stack align="center" gap={6} py="xl">
      <ThemeIcon variant="light" color="gray" size={44} radius="xl">
        {icon ?? <IconInbox size={22} stroke={1.75} />}
      </ThemeIcon>
      <Text fw={600}>{title}</Text>
      {hint && (
        <Text size="sm" c="dimmed" ta="center" maw={360}>
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
