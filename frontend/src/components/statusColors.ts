// Single source of truth for what a status colour MEANS across the dashboard. Add a status here, never per page.
//   yellow = pending, blue = confirmed/info, cyan = arrived, teal = done/success/connected,
//   red = cancelled/failed/error, orange = needs attention, gray = inactive/draft, violet = premium.
//   Inbox: blue = a human owns it, gray = the AI, orange = waiting for a person, yellow = pending/simulated.
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
  no_show: 'orange',
  failed: 'red',
  error: 'red',
  open: 'orange',
  draft: 'gray',
  archived: 'gray',
  inactive: 'gray',
  free: 'gray',
  premium: 'violet',
  // inbox: who owns a conversation / what happened to a sent message
  human: 'blue',
  ai: 'gray',
  waiting: 'orange',
  simulated: 'yellow',
  suppressed: 'gray',
  // inbox: automatic buying-intent triage (app/services/lead_service.py)
  high: 'green',
}

export function statusColor(status: string): string {
  return STATUS_COLOR[status.toLowerCase()] ?? 'gray'
}
