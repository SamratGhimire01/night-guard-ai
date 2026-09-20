import type { ReactNode } from 'react'
import { Group, Text, Title } from '@mantine/core'

interface PageHeaderProps {
  title: string
  description?: ReactNode
  actions?: ReactNode
}

// wrap so the actions drop under the title on narrow screens instead of squeezing it.
export default function PageHeader({ title, description, actions }: PageHeaderProps) {
  return (
    <Group justify="space-between" align="flex-start" wrap="wrap" gap="sm">
      <div style={{ minWidth: 0, flex: '1 1 260px' }}>
        <Title order={2}>{title}</Title>
        {description && (
          <Text c="dimmed" size="sm" mt={4}>
            {description}
          </Text>
        )}
      </div>
      {actions && <Group gap="xs">{actions}</Group>}
    </Group>
  )
}
