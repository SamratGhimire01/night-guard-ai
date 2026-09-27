import { IconBrandFacebook, IconBrandInstagram, IconBrandWhatsapp, IconWorld } from '@tabler/icons-react'
import type { InboxSender } from '../../../api/types'

export const CHANNELS: Record<string, { label: string; color: string; icon: typeof IconWorld }> = {
  whatsapp: { label: 'WhatsApp', color: 'green', icon: IconBrandWhatsapp },
  messenger: { label: 'Messenger', color: 'blue', icon: IconBrandFacebook },
  instagram: { label: 'Instagram', color: 'grape', icon: IconBrandInstagram },
  website: { label: 'Website', color: 'gray', icon: IconWorld },
}

export function channelInfo(channel: string) {
  return CHANNELS[channel] ?? { label: channel, color: 'gray', icon: IconWorld }
}

/** "now", "5m", "3h", "Sep 18" — compact, for the conversation list. */
export function relativeTime(iso: string): string {
  const seconds = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000)
  if (seconds < 60) return 'now'
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h`
  return new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

export function clockTime(iso: string): string {
  return new Date(iso).toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })
}

export function dayLabel(iso: string): string {
  const d = new Date(iso)
  const today = new Date()
  if (d.toDateString() === today.toDateString()) return 'Today'
  const yesterday = new Date(Date.now() - 86400000)
  if (d.toDateString() === yesterday.toDateString()) return 'Yesterday'
  return d.toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' })
}

export function senderPrefix(sender: InboxSender): string {
  return sender === 'staff' ? 'Team: ' : sender === 'agent' ? 'AI: ' : ''
}

/** A staff member's display name from their login email ("sita.k@x.com" -> "sita.k"). */
export function nameFromEmail(email: string | null): string {
  return email ? email.split('@')[0] : 'A staff member'
}
