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
    <Group justify="space-between" align="flex-end" wrap="wrap" gap="md">
      <div style={{ minWidth: 0, flex: '1 1 300px' }}>
        <Title order={2} style={{ letterSpacing: '-0.02em', textWrap: 'balance' }}>
          {title}
        </Title>
        {description && (
          <Text c="dimmed" size="md" mt={6} maw={760}>
            {description}
          </Text>
        )}
      </div>
      {actions && <Group gap="sm">{actions}</Group>}
    </Group>
  )
}
