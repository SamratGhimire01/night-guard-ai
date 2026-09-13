import { useEffect, useState } from 'react'
import { useOutletContext } from 'react-router-dom'
import {
  Alert,
  Badge,
  Button,
  Center,
  Loader,
  Paper,
  Select,
  Stack,
  Switch,
  Table,
  Text,
  Title,
} from '@mantine/core'
import { notifications } from '@mantine/notifications'
import { apiFetch, ApiError } from '../../api/client'
import { useAuth } from '../../auth/AuthContext'
import type { BusinessRead, PaymentRead, PlanRead } from '../../api/types'

type DashboardContext = { business: BusinessRead | null; plan: PlanRead | null }

const STATUS_COLORS: Record<PaymentRead['status'], string> = {
  pending: 'yellow',
  completed: 'green',
  failed: 'red',
}

export default function PaymentsPage() {
  const { business, plan } = useOutletContext<DashboardContext>()
  const { role } = useAuth()
  const canWrite = role === 'owner' || role === 'admin'
  const isPremium = plan?.plan === 'premium'

  const [enabled, setEnabled] = useState(business?.payment_collection_enabled ?? false)
  const [provider, setProvider] = useState<string | null>(business?.payment_provider ?? null)
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
        body: JSON.stringify({ payment_collection_enabled: enabled, payment_provider: enabled ? provider : null }),
      })
      setEnabled(updated.payment_collection_enabled)
      setProvider(updated.payment_provider)
      notifications.show({ message: 'Payment settings saved.', color: 'green' })
    } catch (err) {
      notifications.show({ message: err instanceof ApiError ? err.message : 'Save failed.', color: 'red' })
    } finally {
      setSaving(false)
    }
  }

  const nonNpr = business != null && business.currency !== 'NPR'

  return (
    <Stack gap="md">
      <Title order={2}>Payments</Title>
      <Text c="dimmed" size="sm">
        Collect a real deposit through eSewa or Khalti after a booking is confirmed — configured per-service under
        Services (a service with no deposit configured is always paid in person, unaffected by this setting).
      </Text>

      {!isPremium && (
        <Alert color="grape" title="Upgrade to Premium" variant="light">
          Online payment collection is a Premium-plan feature. Ask an owner on your team to upgrade the business's
          plan to enable it.
        </Alert>
      )}

      {nonNpr && (
        <Alert color="yellow" title="NPR currency required" variant="light">
          eSewa and Khalti only process NPR. Switch this business's currency to NPR under Settings before enabling
          payment collection.
        </Alert>
      )}

      <Paper withBorder p="md" radius="md" maw={480}>
        <Stack gap="sm">
          <Switch
            label="Collect a real deposit online"
            checked={enabled}
            disabled={!canWrite || !isPremium || nonNpr}
            onChange={(e) => setEnabled(e.currentTarget.checked)}
          />
          {enabled && (
            <Select
              label="Payment gateway"
              placeholder="Choose a gateway"
              data={[
                { value: 'esewa', label: 'eSewa' },
                { value: 'khalti', label: 'Khalti' },
              ]}
              value={provider}
              onChange={setProvider}
              disabled={!canWrite}
            />
          )}
          {canWrite && (
            <Button onClick={handleSave} loading={saving} disabled={!isPremium || nonNpr || (enabled && !provider)}>
              Save
            </Button>
          )}
        </Stack>
      </Paper>

      <Title order={4} mt="sm">
        Payment history
      </Title>
      <Table.ScrollContainer minWidth={600}>
        <Table verticalSpacing="sm">
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
            {loading && (
              <Table.Tr>
                <Table.Td colSpan={5}>
                  <Center py="md">
                    <Loader size="sm" />
                  </Center>
                </Table.Td>
              </Table.Tr>
            )}
            {!loading && payments.length === 0 && (
              <Table.Tr>
                <Table.Td colSpan={5}>
                  <Text c="dimmed" ta="center" py="md">
                    No payments yet.
                  </Text>
                </Table.Td>
              </Table.Tr>
            )}
            {payments.map((p) => (
              <Table.Tr key={p.id}>
                <Table.Td style={{ textTransform: 'capitalize' }}>{p.provider}</Table.Td>
                <Table.Td>
                  {p.currency} {p.amount}
                </Table.Td>
                <Table.Td>
                  <Badge color={STATUS_COLORS[p.status]} variant="light">
                    {p.status}
                  </Badge>
                </Table.Td>
                <Table.Td>{p.gateway_reference ?? '—'}</Table.Td>
                <Table.Td>
                  {p.status === 'pending' ? (
                    <a href={p.payment_url} target="_blank" rel="noreferrer">
                      Open
                    </a>
                  ) : (
                    '—'
                  )}
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>
    </Stack>
  )
}
