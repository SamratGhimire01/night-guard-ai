import { useEffect, useState } from 'react'
import { useOutletContext } from 'react-router-dom'
import { Alert, Anchor, Button, Paper, Stack, Switch, Table, Title } from '@mantine/core'
import { notifications } from '@mantine/notifications'
import { IconAlertTriangle, IconCreditCard, IconExternalLink, IconSparkles } from '@tabler/icons-react'
import { apiFetch, ApiError } from '../../api/client'
import { useAuth } from '../../auth/AuthContext'
import type { BusinessRead, PaymentRead, PlanRead } from '../../api/types'
import { EmptyRow } from '../../components/EmptyState'
import PageHeader from '../../components/PageHeader'
import StatusBadge from '../../components/StatusBadge'
import TableSkeleton from '../../components/TableSkeleton'

const GATEWAYS = [
  { value: 'esewa', label: 'eSewa' },
  { value: 'khalti', label: 'Khalti' },
]

type DashboardContext = { business: BusinessRead | null; plan: PlanRead | null }

export default function PaymentsPage() {
  const { business, plan } = useOutletContext<DashboardContext>()
  const { role } = useAuth()
  const canWrite = role === 'owner' || role === 'admin'
  const isPremium = plan?.plan === 'premium'

  const [enabled, setEnabled] = useState(business?.payment_collection_enabled ?? false)
  const [providers, setProviders] = useState<string[]>(business?.payment_providers ?? [])
  const [saving, setSaving] = useState(false)
  const [payments, setPayments] = useState<PaymentRead[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    apiFetch<PaymentRead[]>('/payments')
      .then(setPayments)
      .finally(() => setLoading(false))
  }, [])

  async function handleSave() {
    setSaving(true)
    try {
      const updated = await apiFetch<BusinessRead>('/business/payment-settings', {
        method: 'PATCH',
        body: JSON.stringify({ payment_collection_enabled: enabled, payment_providers: enabled ? providers : [] }),
      })
      setEnabled(updated.payment_collection_enabled)
      setProviders(updated.payment_providers)
      notifications.show({ message: 'Payment settings saved.', color: 'green' })
    } catch (err) {
      notifications.show({ message: err instanceof ApiError ? err.message : 'Save failed.', color: 'red' })
    } finally {
      setSaving(false)
    }
  }

  function toggleProvider(value: string, on: boolean) {
    setProviders((prev) => (on ? [...new Set([...prev, value])] : prev.filter((p) => p !== value)))
  }

  const nonNpr = business != null && business.currency !== 'NPR'

  return (
    <Stack gap="md">
      <PageHeader
        title="Payments"
        description="Collect a real deposit through eSewa or Khalti after a booking is confirmed — configured per-service under Services (a service with no deposit configured is always paid in person, unaffected by this setting)."
      />

      {!isPremium && (
        <Alert color="violet" title="Upgrade to Premium" variant="light" icon={<IconSparkles size={18} stroke={1.75} />}>
          Online payment collection is a Premium-plan feature. Ask an owner on your team to upgrade the business's
          plan to enable it.
        </Alert>
      )}

      {nonNpr && (
        <Alert color="yellow" title="NPR currency required" variant="light" icon={<IconAlertTriangle size={18} stroke={1.75} />}>
          eSewa and Khalti only process NPR. Switch this business's currency to NPR under Settings before enabling
          payment collection.
        </Alert>
      )}

      <Paper p="md" maw={640}>
        <Stack gap="sm">
          <Title order={4}>Online deposits</Title>
          <Switch
            label="Collect a real deposit online"
            checked={enabled}
            disabled={!canWrite || !isPremium || nonNpr}
            onChange={(e) => setEnabled(e.currentTarget.checked)}
          />
          {enabled && (
            <Stack gap="xs" pl="md">
              {GATEWAYS.map((g) => (
                <Switch
                  key={g.value}
                  label={g.label}
                  checked={providers.includes(g.value)}
                  disabled={!canWrite}
                  onChange={(e) => toggleProvider(g.value, e.currentTarget.checked)}
                />
              ))}
              {providers.length > 1 && (
                <Alert variant="light" color="blue">
                  With both on, customers booking in chat are asked which one they'd like to use.
                </Alert>
              )}
            </Stack>
          )}
          {canWrite && (
            <Button
              onClick={handleSave}
              loading={saving}
              disabled={!isPremium || nonNpr || (enabled && providers.length === 0)}
              w="fit-content"
            >
              Save
            </Button>
          )}
        </Stack>
      </Paper>

      <Title order={3} mt="sm">
        Payment history
      </Title>
      <Paper p={0} style={{ overflow: 'hidden' }}>
        <Table.ScrollContainer minWidth={600}>
          <Table>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Provider</Table.Th>
                <Table.Th>Amount</Table.Th>
                <Table.Th>Status</Table.Th>
                <Table.Th>Gateway reference</Table.Th>
                <Table.Th>Payment link</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {loading && <TableSkeleton cols={5} />}
              {!loading && payments.length === 0 && (
                <EmptyRow
                  colSpan={5}
                  icon={<IconCreditCard size={22} stroke={1.75} />}
                  title="No payments yet"
                  hint="Deposits collected through eSewa or Khalti will appear here."
                />
              )}
              {payments.map((p) => (
                <Table.Tr key={p.id}>
                  <Table.Td style={{ textTransform: 'capitalize' }}>{p.provider}</Table.Td>
                  <Table.Td style={{ whiteSpace: 'nowrap' }}>
                    {p.currency} {p.amount}
                  </Table.Td>
                  <Table.Td>
                    <StatusBadge status={p.status} />
                  </Table.Td>
                  <Table.Td>{p.gateway_reference ?? '—'}</Table.Td>
                  <Table.Td>
                    {p.status === 'pending' ? (
                      <Anchor href={p.payment_url} target="_blank" rel="noreferrer" size="sm">
                        Open <IconExternalLink size={14} style={{ verticalAlign: '-2px' }} />
                      </Anchor>
                    ) : (
                      '—'
                    )}
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      </Paper>
    </Stack>
  )
}
