// Single source of truth for what a status colour MEANS across the dashboard. Add a status here, never per page.
//   yellow = pending, blue = confirmed/info, cyan = arrived, teal = done/success/connected,
//   red = cancelled/failed/error, orange = needs attention, gray = inactive/draft, violet = premium.
const STATUS_COLOR: Record<string, string> = {
  pending: 'yellow',
  confirmed: 'blue',
  arrived: 'cyan',
  completed: 'teal',
  resolved: 'teal',
  approved: 'teal',
  sent: 'teal',
  connected: 'teal',
  cancelled: 'red',
  failed: 'red',
  error: 'red',
  open: 'orange',
  draft: 'gray',
  archived: 'gray',
  inactive: 'gray',
  free: 'gray',
  premium: 'violet',
}

export function statusColor(status: string): string {
  return STATUS_COLOR[status.toLowerCase()] ?? 'gray'
}
