import { useEffect, useMemo, useState } from 'react'
import { useOutletContext } from 'react-router-dom'
import { Alert, Group, Paper, Select, SegmentedControl, SimpleGrid, Skeleton, Stack, Text, Title, Tooltip } from '@mantine/core'
import { BarChart } from '@mantine/charts'
import { IconAlertTriangle, IconCalendarStats, IconClockHour4, IconCoinOff, IconFlame, IconUserOff } from '@tabler/icons-react'
import { apiFetch, ApiError } from '../../api/client'
import { useAuth } from '../../auth/AuthContext'
import type { BusinessRead } from '../../api/types'
import PageHeader from '../../components/PageHeader'
import StatCard from '../../components/StatCard'
import StatusBadge from '../../components/StatusBadge'

type DashboardContext = { business: BusinessRead | null }
type Granularity = 'day' | 'week' | 'month'

// Shape of GET /reports/analytics (backend/app/services/reporting/analytics_service.py).
interface BookingAnalytics {
  timezone: string
  date_from: string
  date_to: string
  granularity: Granularity
  total_bookings: number
  bookings_trend: { period: string; bookings: number }[]
  outcomes: Record<string, number>
  no_show_rate: number | null
  no_show_denominator: number
  median_lead_time_hours: number | null
  lead_time_sample_size: number
  forfeited_deposits: { currency: string; total: string; count: number }[]
  popular_slots: { weekday: number; hour: number; count: number }[]
}

const ICON = { size: 20, stroke: 1.75 }
const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
const RANGES = [
  { value: '30', label: 'Last 30 days' },
  { value: '90', label: 'Last 90 days' },
  { value: '365', label: 'Last 12 months' },
]
const OUTCOME_ORDER = ['completed', 'arrived', 'no_show', 'confirmed', 'cancelled']

function hourLabel(h: number) {
  const suffix = h < 12 ? 'am' : 'pm'
  return `${h % 12 === 0 ? 12 : h % 12}${suffix}`
}

function formatLeadTime(hours: number | null): string {
  if (hours === null) return '—'
  if (hours < 1) return `${Math.round(hours * 60)} min`
  if (hours < 48) return `${hours} hr`
  return `${Math.round((hours / 24) * 10) / 10} days`
}

// e.g. "NPR 1,200". A range with no forfeited deposit shows the business's own currency at 0 rather than a bare dash.
function formatForfeited(items: BookingAnalytics['forfeited_deposits'], fallbackCurrency: string): string {
  if (items.length === 0) return `${fallbackCurrency} 0`
  return items.map((f) => `${f.currency} ${Number(f.total).toLocaleString('en-US', { maximumFractionDigits: 2 })}`).join(' + ')
}

function formatPeriod(period: string, granularity: Granularity): string {
  const d = new Date(`${period}T00:00:00`)
  if (granularity === 'month') return d.toLocaleDateString('en-US', { month: 'short', year: '2-digit' })
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

// Today's date in the BUSINESS's timezone, so "last 30 days" matches what the backend buckets by.
function todayIn(timeZone: string): Date {
  const [y, m, d] = new Intl.DateTimeFormat('en-CA', { timeZone }).format(new Date()).split('-').map(Number)
  return new Date(Date.UTC(y, m - 1, d))
}
const iso = (d: Date) => d.toISOString().slice(0, 10)

/** Weekday x hour grid. Colour intensity = share of the busiest cell, so the pattern reads at a glance. */
function SlotHeatmap({ slots }: { slots: BookingAnalytics['popular_slots'] }) {
  const counts = useMemo(() => new Map(slots.map((s) => [`${s.weekday}-${s.hour}`, s.count])), [slots])
  const max = Math.max(1, ...slots.map((s) => s.count))
  // Show the hours the business actually books in (plus a little padding), not all 24 columns of mostly nothing.
  const hours = slots.map((s) => s.hour)
  const first = hours.length ? Math.max(0, Math.min(...hours) - 1) : 8
  const last = hours.length ? Math.min(23, Math.max(...hours) + 1) : 18
  const cols = Array.from({ length: last - first + 1 }, (_, i) => first + i)

  return (
    <div style={{ overflowX: 'auto' }}>
      <div
        role="table"
        aria-label="Bookings by weekday and hour"
        style={{ display: 'grid', gridTemplateColumns: `44px repeat(${cols.length}, minmax(34px, 1fr))`, gap: 4, minWidth: 44 + cols.length * 38 }}
      >
        <div />
        {cols.map((h) => (
          <Text key={h} size="xs" c="dimmed" ta="center">
            {hourLabel(h)}
          </Text>
        ))}
        {WEEKDAYS.map((day, weekday) => (
          <div key={day} style={{ display: 'contents' }} role="row">
            <Text size="xs" c="dimmed" style={{ alignSelf: 'center' }}>
              {day}
            </Text>
            {cols.map((h) => {
              const n = counts.get(`${weekday}-${h}`) ?? 0
              return (
                <Tooltip key={h} label={`${day} ${hourLabel(h)} — ${n} booking${n === 1 ? '' : 's'}`} withArrow openDelay={100}>
                  <div
                    role="cell"
                    aria-label={`${day} ${hourLabel(h)}: ${n}`}
                    style={{
                      height: 34,
                      borderRadius: 6,
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      fontSize: 12,
                      fontWeight: 600,
                      fontVariantNumeric: 'tabular-nums',
                      background:
                        n === 0
                          ? 'var(--mantine-color-default-hover)'
                          : `color-mix(in srgb, var(--mantine-color-brand-filled) ${Math.round(20 + (n / max) * 80)}%, transparent)`,
                      color: n / max > 0.55 ? 'white' : 'var(--mantine-color-text)',
                    }}
                  >
                    {n > 0 ? n : ''}
                  </div>
                </Tooltip>
              )
            })}
          </div>
        ))}
      </div>
      <Group gap={6} mt="sm" justify="flex-end">
        <Text size="xs" c="dimmed">
          Fewer
        </Text>
        {[0.2, 0.4, 0.6, 0.8, 1].map((f) => (
          <div
            key={f}
            style={{ width: 18, height: 12, borderRadius: 3, background: `color-mix(in srgb, var(--mantine-color-brand-filled) ${Math.round(f * 100)}%, transparent)` }}
          />
        ))}
        <Text size="xs" c="dimmed">
          More
        </Text>
      </Group>
    </div>
  )
}

export default function AnalyticsPage() {
  const { role } = useAuth()
  const { business } = useOutletContext<DashboardContext>()
  const timezone = business?.timezone ?? 'UTC'
  const allowed = role === 'owner' || role === 'admin'

  const [days, setDays] = useState<string>('90')
  const [granularity, setGranularity] = useState<Granularity>('week')
  const [data, setData] = useState<BookingAnalytics | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!allowed) return
    const to = todayIn(timezone)
    const from = new Date(to)
    from.setUTCDate(from.getUTCDate() - (Number(days) - 1))
    let cancelled = false
    apiFetch<BookingAnalytics>(`/reports/analytics?date_from=${iso(from)}&date_to=${iso(to)}&granularity=${granularity}`)
      .then((d) => {
        if (!cancelled) {
          setData(d)
          setError(null)
        }
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof ApiError ? err.message : 'Could not load analytics.')
      })
    return () => {
      cancelled = true
    }
  }, [allowed, days, granularity, timezone])

  const busiest = useMemo(() => {
    const top = data?.popular_slots.reduce<BookingAnalytics['popular_slots'][number] | null>(
      (best, s) => (best === null || s.count > best.count ? s : best),
      null
    )
    return top ? `${WEEKDAYS[top.weekday]} ${hourLabel(top.hour)}` : '—'
  }, [data])

  const header = (
    <PageHeader
      title="Analytics"
      description={`How your bookings are trending and when people book. Times are in ${timezone}.`}
      actions={
        allowed && (
          <>
            <Select data={RANGES} value={days} onChange={(v) => v && setDays(v)} allowDeselect={false} w={160} aria-label="Date range" />
            <SegmentedControl
              value={granularity}
              onChange={(v) => setGranularity(v as Granularity)}
              data={[
                { value: 'day', label: 'Day' },
                { value: 'week', label: 'Week' },
                { value: 'month', label: 'Month' },
              ]}
            />
          </>
        )
      }
    />
  )

  if (!allowed) {
    return (
      <Stack gap="md">
        {header}
        <Alert color="yellow" icon={<IconAlertTriangle size={18} stroke={1.75} />} title="Owners and admins only">
          Analytics include business performance data, so only owners and admins can see them.
        </Alert>
      </Stack>
    )
  }

  if (error) {
    return (
      <Stack gap="md">
        {header}
        <Alert color="red" icon={<IconAlertTriangle size={18} stroke={1.75} />} title="Couldn't load analytics">
          {error}
        </Alert>
      </Stack>
    )
  }

  if (!data) {
    return (
      <Stack gap="md">
        {header}
        <SimpleGrid cols={{ base: 2, md: 4 }}>
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} height={110} radius="md" />
          ))}
        </SimpleGrid>
        <Skeleton height={320} radius="md" />
        <Skeleton height={300} radius="md" />
      </Stack>
    )
  }

  const trend = data.bookings_trend.map((t) => ({ period: formatPeriod(t.period, data.granularity), Bookings: t.bookings }))
  const noShowNote =
    data.no_show_rate === null
      ? 'No appointment in this range has a recorded outcome yet.'
      : `${data.outcomes.no_show ?? 0} of ${data.no_show_denominator} appointments with a recorded outcome (completed, arrived or no-show).`

  return (
    <Stack gap="lg">
      {header}

      <SimpleGrid cols={{ base: 2, sm: 3, lg: 5 }}>
        <StatCard label="Bookings" value={data.total_bookings} icon={<IconCalendarStats {...ICON} />} />
        <StatCard
          label="No-show rate"
          value={data.no_show_rate === null ? '—' : `${data.no_show_rate}%`}
          icon={<IconUserOff {...ICON} />}
          color="orange"
        />
        <StatCard
          label="Median booking lead time"
          value={formatLeadTime(data.median_lead_time_hours)}
          icon={<IconClockHour4 {...ICON} />}
          color="teal"
        />
        <StatCard label="Busiest time slot" value={busiest} icon={<IconFlame {...ICON} />} color="grape" />
        <StatCard
          label="Forfeited deposits"
          value={formatForfeited(data.forfeited_deposits, business?.currency ?? '')}
          icon={<IconCoinOff {...ICON} />}
          color="red"
        />
      </SimpleGrid>
      <Text size="xs" c="dimmed" mt={-8}>
        {noShowNote} Forfeited deposits are paid deposits kept because the appointment became a no-show
        {data.forfeited_deposits.length > 0 ? ` (${data.forfeited_deposits.reduce((n, f) => n + f.count, 0)} in this range)` : ''}.
        Lead time is the median gap between when a booking was made and its appointment time
        {data.lead_time_sample_size > 0 ? ` (${data.lead_time_sample_size} bookings)` : ''} — a median, so a few far-ahead bookings don't skew it.
      </Text>

      <Paper p="md">
        <Group justify="space-between" mb="sm" wrap="wrap">
          <Title order={4}>Bookings per {data.granularity}</Title>
          <Group gap="xs">
            {OUTCOME_ORDER.filter((s) => (data.outcomes[s] ?? 0) > 0).map((s) => (
              <Tooltip key={s} label={`${data.outcomes[s]} ${s.replace('_', '-')} in this range`} withArrow>
                <span>
                  <StatusBadge status={s} label={`${s.replace('_', '-')} ${data.outcomes[s]}`} />
                </span>
              </Tooltip>
            ))}
          </Group>
        </Group>
        {data.total_bookings === 0 ? (
          <Text c="dimmed" ta="center" py="xl">
            No bookings in this range.
          </Text>
        ) : (
          <BarChart h={300} data={trend} dataKey="period" series={[{ name: 'Bookings', color: 'brand.5' }]} tickLine="y" gridAxis="y" withTooltip />
        )}
      </Paper>

      <Paper p="md">
        <Title order={4} mb={4}>
          Most popular time slots
        </Title>
        <Text size="sm" c="dimmed" mb="md">
          Bookings by day of week and hour, {data.date_from} to {data.date_to}.
        </Text>
        {data.popular_slots.length === 0 ? (
          <Text c="dimmed" ta="center" py="xl">
            No bookings in this range.
          </Text>
        ) : (
          <SlotHeatmap slots={data.popular_slots} />
        )}
      </Paper>
    </Stack>
  )
}
