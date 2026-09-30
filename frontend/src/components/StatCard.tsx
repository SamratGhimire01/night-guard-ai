import type { ReactNode } from 'react'
import { Paper, Text } from '@mantine/core'

interface StatCardProps {
  label: string
  value: string | number
  icon?: ReactNode
  /** Mantine colour name for the icon tile; defaults to the brand colour. */
  color?: string
}

// Icon tile sits above the label so labels get the full card width instead of wrapping beside it.
// Long values (e.g. "NPR 116,500") step down a size so they never overflow the card.
export default function StatCard({ label, value, icon, color = 'brand' }: StatCardProps) {
  const tint = `linear-gradient(135deg, var(--mantine-color-${color}-4), var(--mantine-color-${color}-7))`
  return (
    <Paper p="lg" className="ng-lift" style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      {icon && (
        <span className="ng-tile" style={{ width: 42, height: 42, borderRadius: 13, background: tint, marginBottom: 14 }}>
          {icon}
        </span>
      )}
      <Text size="sm" c="dimmed" fw={600}>
        {label}
      </Text>
      <Text
        fz={String(value).length > 9 ? 22 : 32}
        fw={800}
        mt="auto"
        pt={4}
        lh={1.15}
        style={{ fontVariantNumeric: 'tabular-nums', letterSpacing: '-0.01em' }}
      >
        {value}
      </Text>
    </Paper>
  )
}
