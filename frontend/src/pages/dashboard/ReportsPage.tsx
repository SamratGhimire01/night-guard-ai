import { useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { useOutletContext } from 'react-router-dom'
import { Alert, Badge, Button, Group, NumberInput, Paper, SimpleGrid, Stack, Tabs, Text, Title } from '@mantine/core'
import { BarChart, PieChart } from '@mantine/charts'
import { notifications } from '@mantine/notifications'
import { apiFetch, ApiError, downloadFile } from '../../api/client'
import type {
  BusinessRead,
  DailyReport,
  MonthlyReport,
  PlanRead,
  RevenueEstimate,
  YearlyReport,
  YearOverYear,
  YearOverYearMetric,
} from '../../api/types'

type DashboardContext = { business: BusinessRead | null; plan: PlanRead | null }

const STATUS_COLORS: Record<string, string> = { confirmed: 'blue', cancelled: 'red', completed: 'teal' }
const PIE_PALETTE = ['blue.6', 'grape.6', 'teal.6', 'orange.6', 'red.6', 'yellow.6', 'cyan.6']

function money(value: string | number) {
  return `$${Number(value).toFixed(2)}`
}

function StatCard({ label, value }: { label: string; value: ReactNode }) {
  return (
    <Paper withBorder p="sm" radius="md">
      <Text size="xs" c="dimmed">
        {label}
      </Text>
      <Text size="xl" fw={700}>
        {value}
      </Text>
    </Paper>
  )
}

function RevenueCallout({ revenue }: { revenue: RevenueEstimate }) {
  return (
    <Paper withBorder p="md" radius="md">
      <Text size="xs" c="dimmed" fw={600} tt="uppercase">
        Estimated billed value
      </Text>
      <Text size="xl" fw={700}>
        {money(revenue.value)}
      </Text>
      <Text size="xs" c="dimmed" mt={4}>
        Based on {revenue.appointment_count} non-cancelled appointment{revenue.appointment_count === 1 ? '' : 's'}.{' '}
        {revenue.definition}
      </Text>
    </Paper>
  )
}

function YoYStat({ label, metric, isMoney }: { label: string; metric: YearOverYearMetric; isMoney?: boolean }) {
  const pct = metric.change_pct
  const color = pct == null ? 'gray' : pct > 0 ? 'green' : pct < 0 ? 'red' : 'gray'
  const format = (v: number | string) => (isMoney ? money(v) : String(v))
  return (
    <div>
      <Text size="xs" c="dimmed">
        {label}
      </Text>
      <Text size="lg" fw={700}>
        {format(metric.current)}
      </Text>
      <Group gap={4}>
        <Text size="xs" c="dimmed">
          was {format(metric.prior)}
        </Text>
        {pct != null && (
          <Badge color={color} size="sm" variant="light">
            {pct >= 0 ? '+' : ''}
            {(pct * 100).toFixed(1)}%
          </Badge>
        )}
      </Group>
    </div>
  )
}

function YearOverYearCard({ yoy }: { yoy: YearOverYear }) {
  if (!yoy.available) {
    return (
      <Alert color="gray" title={`No ${yoy.prior_year} data`}>
        {yoy.note}
      </Alert>
    )
  }
  return (
    <Paper withBorder p="md" radius="md">
      <Text fw={600} mb="sm">
        Year-over-year vs {yoy.prior_year}
      </Text>
      <SimpleGrid cols={{ base: 1, sm: 3 }}>
        <YoYStat label="Appointments Scheduled" metric={yoy.appointments_scheduled} />
        <YoYStat label="Revenue Estimate" metric={yoy.revenue_estimate} isMoney />
        <YoYStat label="New Customers" metric={yoy.new_customers} />
      </SimpleGrid>
    </Paper>
  )
}

function hourInTimezone(iso: string, timezone: string): number {
  return Number(
    new Intl.DateTimeFormat('en-US', { hour: 'numeric', hour12: false, timeZone: timezone }).format(new Date(iso)),
  ) % 24
}

function todayIso() {
  return new Date().toISOString().slice(0, 10)
}

function thisMonthValue() {
  return new Date().toISOString().slice(0, 7)
}

// --- Daily -----------------------------------------------------------------

function DailyReportPanel({ business }: { business: BusinessRead | null }) {
  const [date, setDate] = useState(todayIso)
  const [report, setReport] = useState<DailyReport | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    apiFetch<DailyReport>(`/reports/daily?date=${date}`)
      .then((r) => {
        if (!cancelled) setReport(r)
      })
      .catch((err) => {
        if (!cancelled) notifications.show({ message: err instanceof ApiError ? err.message : 'Failed to load report.', color: 'red' })
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [date])

  const hourData = useMemo(() => {
    if (!report) return []
    const tz = business?.timezone ?? 'UTC'
    const counts = new Map<number, number>()
    for (const a of report.appointments) {
      if (a.status === 'cancelled') continue
      const hour = hourInTimezone(a.scheduled_at, tz)
      counts.set(hour, (counts.get(hour) ?? 0) + 1)
    }
    return [...counts.entries()].sort((a, b) => a[0] - b[0]).map(([hour, count]) => ({ hour: `${hour}:00`, Appointments: count }))
  }, [report, business])

  const statusData = useMemo(() => {
    if (!report) return []
    return Object.entries(report.summary.appointments_by_status).map(([status, count], i) => ({
      name: status,
      value: count,
      color: STATUS_COLORS[status] ?? PIE_PALETTE[i % PIE_PALETTE.length],
    }))
  }, [report])

  async function handleDownload() {
    try {
      await downloadFile(`/reports/daily/excel?date=${date}`, `daily_report_${date}.xlsx`)
    } catch (err) {
      notifications.show({ message: err instanceof ApiError ? err.message : 'Download failed.', color: 'red' })
    }
  }

  return (
    <Stack gap="md">
      <Group justify="space-between" wrap="wrap">
        <input
          type="date"
          value={date}
          onChange={(e) => setDate(e.target.value)}
          style={{ padding: 6, fontSize: 14, border: '1px solid #ced4da', borderRadius: 4 }}
        />
        <Button variant="light" onClick={handleDownload}>
          Download Excel
        </Button>
      </Group>

      {report && !loading && (
        <>
          <SimpleGrid cols={{ base: 2, sm: 5 }}>
            <StatCard label="Scheduled" value={report.summary.appointments_scheduled} />
            <StatCard label="Cancellations" value={report.summary.cancellations} />
            <StatCard label="Reschedules" value={report.summary.reschedules} />
            <StatCard label="New Leads" value={report.summary.new_leads} />
            <StatCard label="Human Review Open" value={report.summary.human_review_open_count} />
          </SimpleGrid>

          <RevenueCallout revenue={report.revenue_estimate} />

          <SimpleGrid cols={{ base: 1, md: 2 }}>
            <Paper withBorder p="md" radius="md">
              <Text fw={600} mb="xs">
                Appointments by hour
              </Text>
              {hourData.length > 0 ? (
                <BarChart h={260} data={hourData} dataKey="hour" series={[{ name: 'Appointments', color: 'blue.6' }]} withBarValueLabel />
              ) : (
                <Text c="dimmed" ta="center" py="xl">
                  No appointments scheduled for this day.
                </Text>
              )}
            </Paper>
            <Paper withBorder p="md" radius="md">
              <Text fw={600} mb="xs">
                Status mix
              </Text>
              {statusData.length > 0 ? (
                <PieChart data={statusData} withLabels withTooltip size={220} />
              ) : (
                <Text c="dimmed" ta="center" py="xl">
                  No activity to chart for this day.
                </Text>
              )}
            </Paper>
          </SimpleGrid>
        </>
      )}
    </Stack>
  )
}

// --- Monthly -----------------------------------------------------------------

function MonthlyReportPanel() {
  const [month, setMonth] = useState(thisMonthValue)
  const [report, setReport] = useState<MonthlyReport | null>(null)
  const [loading, setLoading] = useState(true)
  const [year, monthNum] = month.split('-').map(Number)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    apiFetch<MonthlyReport>(`/reports/monthly?year=${year}&month=${monthNum}`)
      .then((r) => {
        if (!cancelled) setReport(r)
      })
      .catch((err) => {
        if (!cancelled) notifications.show({ message: err instanceof ApiError ? err.message : 'Failed to load report.', color: 'red' })
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [month])

  const dayData = useMemo(() => report?.busiest_days.map((d) => ({ day: d.day.slice(0, 3), Appointments: d.count })) ?? [], [report])
  const serviceData = useMemo(
    () =>
      (report?.most_requested_services ?? []).map((s, i) => ({
        name: s.service_name ?? 'Deleted service',
        value: s.count,
        color: PIE_PALETTE[i % PIE_PALETTE.length],
      })),
    [report],
  )
  const hasScheduleActivity = (report?.appointments.scheduled_for_month ?? 0) > 0

  async function handleDownload() {
    try {
      await downloadFile(`/reports/monthly/excel?year=${year}&month=${monthNum}`, `monthly_report_${month}.xlsx`)
    } catch (err) {
      notifications.show({ message: err instanceof ApiError ? err.message : 'Download failed.', color: 'red' })
    }
  }

  return (
    <Stack gap="md">
      <Group justify="space-between" wrap="wrap">
        <input
          type="month"
          value={month}
          onChange={(e) => setMonth(e.target.value)}
          style={{ padding: 6, fontSize: 14, border: '1px solid #ced4da', borderRadius: 4 }}
        />
        <Button variant="light" onClick={handleDownload}>
          Download Excel
        </Button>
      </Group>

      {report && !loading && (
        <>
          <SimpleGrid cols={{ base: 2, sm: 4 }}>
            <StatCard label="Requested" value={report.appointments.requested} />
            <StatCard label="Scheduled" value={report.appointments.scheduled_for_month} />
            <StatCard
              label="Cancellation Rate"
              value={report.cancellation_rate.value !== null ? `${(report.cancellation_rate.value * 100).toFixed(1)}%` : 'N/A'}
            />
            <StatCard
              label="Booking Conversion"
              value={report.booking_conversion.value !== null ? `${(report.booking_conversion.value * 100).toFixed(1)}%` : 'N/A'}
            />
          </SimpleGrid>

          <RevenueCallout revenue={report.revenue_estimate} />

          <SimpleGrid cols={{ base: 1, md: 2 }}>
            <Paper withBorder p="md" radius="md">
              <Text fw={600} mb="xs">
                Busiest days
              </Text>
              {hasScheduleActivity ? (
                <BarChart h={260} data={dayData} dataKey="day" series={[{ name: 'Appointments', color: 'grape.6' }]} withBarValueLabel />
              ) : (
                <Text c="dimmed" ta="center" py="xl">
                  No appointments scheduled this month.
                </Text>
              )}
            </Paper>
            <Paper withBorder p="md" radius="md">
              <Text fw={600} mb="xs">
                Service mix
              </Text>
              {serviceData.length > 0 ? (
                <PieChart data={serviceData} withLabels withTooltip withLegend size={220} />
              ) : (
                <Text c="dimmed" ta="center" py="xl">
                  No activity to chart for this month.
                </Text>
              )}
            </Paper>
          </SimpleGrid>
        </>
      )}
    </Stack>
  )
}

// --- Yearly (Premium-gated, real new Phase 37 capability) ------------------

function YearlyReportPanel() {
  const [year, setYear] = useState(() => new Date().getFullYear())
  const [report, setReport] = useState<YearlyReport | null>(null)
  const [upgradeMessage, setUpgradeMessage] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setUpgradeMessage(null)
    setReport(null)
    apiFetch<YearlyReport>(`/reports/yearly?year=${year}`)
      .then((r) => {
        if (!cancelled) setReport(r)
      })
      .catch((err) => {
        if (cancelled) return
        if (err instanceof ApiError && err.status === 402) {
          setUpgradeMessage(err.message)
        } else {
          notifications.show({ message: err instanceof ApiError ? err.message : 'Failed to load report.', color: 'red' })
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [year])

  const monthData = useMemo(
    () => report?.month_by_month.map((m) => ({ month: m.month_name.slice(0, 3), Scheduled: m.appointments_scheduled })) ?? [],
    [report],
  )
  const hasActivity = (report?.appointments.scheduled_for_year ?? 0) > 0

  async function handleDownload() {
    try {
      await downloadFile(`/reports/yearly/excel?year=${year}`, `yearly_report_${year}.xlsx`)
    } catch (err) {
      notifications.show({ message: err instanceof ApiError ? err.message : 'Download failed.', color: 'red' })
    }
  }

  const yearPicker = (
    <NumberInput
      label="Year"
      value={year}
      onChange={(v) => setYear(typeof v === 'number' ? v : Number(v) || year)}
      min={2000}
      max={2100}
      w={140}
      hideControls={false}
    />
  )

  if (!loading && upgradeMessage) {
    return (
      <Stack gap="md">
        {yearPicker}
        <Alert color="grape" title="Upgrade to Premium" variant="light">
          Yearly reports are a Premium-plan feature. {upgradeMessage} Ask an owner on your team to upgrade the
          business's plan to unlock month-by-month trends, year-over-year comparisons, and a real yearly Excel
          export.
        </Alert>
      </Stack>
    )
  }

  return (
    <Stack gap="md">
      <Group justify="space-between" wrap="wrap">
        {yearPicker}
        {report && (
          <Button variant="light" onClick={handleDownload}>
            Download Excel
          </Button>
        )}
      </Group>

      {report && !loading && (
        <>
          <SimpleGrid cols={{ base: 2, sm: 4 }}>
            <StatCard label="Requested" value={report.appointments.requested} />
            <StatCard label="Scheduled" value={report.appointments.scheduled_for_year} />
            <StatCard
              label="Cancellation Rate"
              value={report.cancellation_rate.value !== null ? `${(report.cancellation_rate.value * 100).toFixed(1)}%` : 'N/A'}
            />
            <StatCard
              label="Booking Conversion"
              value={report.booking_conversion.value !== null ? `${(report.booking_conversion.value * 100).toFixed(1)}%` : 'N/A'}
            />
          </SimpleGrid>

          <RevenueCallout revenue={report.revenue_estimate} />

          <Paper withBorder p="md" radius="md">
            <Text fw={600} mb="xs">
              Month-by-month
            </Text>
            {hasActivity ? (
              <BarChart h={260} data={monthData} dataKey="month" series={[{ name: 'Scheduled', color: 'teal.6' }]} withBarValueLabel />
            ) : (
              <Text c="dimmed" ta="center" py="xl">
                No appointments scheduled in {year}.
              </Text>
            )}
          </Paper>

          <YearOverYearCard yoy={report.year_over_year} />
        </>
      )}
    </Stack>
  )
}

export default function ReportsPage() {
  const { business } = useOutletContext<DashboardContext>()

  return (
    <Stack gap="md">
      <Title order={2}>Reports</Title>
      <Tabs defaultValue="daily">
        <Tabs.List>
          <Tabs.Tab value="daily">Daily</Tabs.Tab>
          <Tabs.Tab value="monthly">Monthly</Tabs.Tab>
          <Tabs.Tab value="yearly">Yearly</Tabs.Tab>
        </Tabs.List>
        <Tabs.Panel value="daily" pt="md">
          <DailyReportPanel business={business} />
        </Tabs.Panel>
        <Tabs.Panel value="monthly" pt="md">
          <MonthlyReportPanel />
        </Tabs.Panel>
        <Tabs.Panel value="yearly" pt="md">
          <YearlyReportPanel />
        </Tabs.Panel>
      </Tabs>
    </Stack>
  )
}
