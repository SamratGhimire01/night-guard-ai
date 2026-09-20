import type { ReactNode } from 'react'
import { Paper, Text, ThemeIcon } from '@mantine/core'

interface StatCardProps {
  label: string
  value: string | number
  icon?: ReactNode
  /** Mantine colour name for the icon tint; defaults to the brand colour. */
  color?: string
}

// Icon sits above the label so labels get the full card width instead of wrapping beside it.
// Long values (e.g. "NPR 116,500") step down a size so they never overflow the card.
export default function StatCard({ label, value, icon, color }: StatCardProps) {
  return (
    <Paper p="md" style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      {icon && (
        <ThemeIcon variant="light" color={color} size={34} radius="md" mb="sm">
          {icon}
        </ThemeIcon>
      )}
      <Text size="sm" c="dimmed">
        {label}
      </Text>
      <Text fz={String(value).length > 9 ? 20 : 28} fw={700} mt="auto" pt={2} style={{ fontVariantNumeric: 'tabular-nums' }}>
        {value}
      </Text>
    </Paper>
  )
}
