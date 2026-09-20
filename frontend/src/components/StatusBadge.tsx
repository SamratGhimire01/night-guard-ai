import { Badge, type BadgeProps } from '@mantine/core'
import { statusColor } from './statusColors'

interface StatusBadgeProps extends Omit<BadgeProps, 'color' | 'children'> {
  status: string
  /** Shown text; defaults to the status itself. */
  label?: string
}

export default function StatusBadge({ status, label, ...rest }: StatusBadgeProps) {
  return (
    <Badge color={statusColor(status)} tt="capitalize" miw="max-content" {...rest}>
      {label ?? status}
    </Badge>
  )
}
