import { useEffect, useState } from 'react'
import {
  Button,
  ColorInput,
  Select,
  Skeleton,
  Stack,
  Tabs,
  Text,
  Textarea,
  TextInput,
  Title,
  Tooltip,
} from '@mantine/core'
import { useForm } from '@mantine/form'
import { notifications } from '@mantine/notifications'
import { useAuth } from '../../auth/AuthContext'
import { apiFetch, ApiError } from '../../api/client'
import type { BusinessReferenceData, BusinessRead, BusinessUpdate } from '../../api/types'

const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/

// Friendly labels for the currency dropdown — cosmetic only. The option
// VALUES (and the timezone list entirely) come from GET /business/reference-data,
// i.e. the backend's own real validated sets, not a hand-typed list kept in
// sync by hand. A code with no label here still renders fine (falls back to
// the bare code) if the backend's allowlist ever grows without this map.
const CURRENCY_LABELS: Record<string, string> = {
  USD: 'US Dollar',
  NPR: 'Nepalese Rupee',
  EUR: 'Euro',
  GBP: 'British Pound',
  INR: 'Indian Rupee',
  AUD: 'Australian Dollar',
  CAD: 'Canadian Dollar',
  JPY: 'Japanese Yen',
  CNY: 'Chinese Yuan',
  SGD: 'Singapore Dollar',
}

type ProfileValues = Pick<
  BusinessUpdate,
  'name' | 'description' | 'address' | 'phone' | 'email' | 'website' | 'timezone' | 'currency'
>

export default function SettingsPage() {
  const { role } = useAuth()
  const canWrite = role === 'owner' || role === 'admin'

  const [business, setBusiness] = useState<BusinessRead | null>(null)
  const [refData, setRefData] = useState<BusinessReferenceData | null>(null)

  useEffect(() => {
    apiFetch<BusinessRead>('/business/me').then(setBusiness)
    apiFetch<BusinessReferenceData>('/business/reference-data').then(setRefData)
  }, [])

  const profileForm = useForm<ProfileValues>({
    initialValues: {
      name: '',
      description: '',
      address: '',
      phone: '',
      email: '',
      website: '',
      timezone: '',
      currency: '',
    },
    validate: {
      name: (v) => ((v ?? '').trim() ? null : 'Business name is required.'),
      email: (v) => (!v || EMAIL_RE.test(v) ? null : 'Enter a valid email address (e.g. name@example.com).'),
      timezone: (v) => (v ? null : 'Select a timezone.'),
      currency: (v) => (v ? null : 'Select a currency.'),
    },
  })

  const widgetForm = useForm<Pick<BusinessUpdate, 'brand_color' | 'logo_url'>>({
    initialValues: { brand_color: '#2563eb', logo_url: '' },
  })

  useEffect(() => {
    if (!business) return
    profileForm.setValues({
      name: business.name,
      description: business.description ?? '',
      address: business.address ?? '',
      phone: business.phone ?? '',
      email: business.email ?? '',
      website: business.website ?? '',
      timezone: business.timezone,
      currency: business.currency,
    })
    widgetForm.setValues({ brand_color: business.brand_color, logo_url: business.logo_url ?? '' })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [business])

  async function handleProfileSubmit(values: ProfileValues) {
    try {
      const updated = await apiFetch<BusinessRead>('/business/me', {
        method: 'PATCH',
        body: JSON.stringify({
          name: values.name,
          description: values.description || null,
          address: values.address || null,
          phone: values.phone || null,
          email: values.email || null,
          website: values.website || null,
          timezone: values.timezone,
          currency: values.currency,
        }),
      })
      setBusiness(updated)
      notifications.show({ message: 'Business profile updated.', color: 'green' })
    } catch (err) {
      notifications.show({ message: err instanceof ApiError ? err.message : 'Save failed.', color: 'red' })
    }
  }

  async function handleWidgetSubmit(values: Pick<BusinessUpdate, 'brand_color' | 'logo_url'>) {
    try {
      const updated = await apiFetch<BusinessRead>('/business/me', {
        method: 'PATCH',
        body: JSON.stringify({ brand_color: values.brand_color, logo_url: values.logo_url || null }),
      })
      setBusiness(updated)
      notifications.show({ message: 'Branding updated — your website widget reflects this immediately.', color: 'green' })
    } catch (err) {
      notifications.show({ message: err instanceof ApiError ? err.message : 'Save failed.', color: 'red' })
    }
  }

  if (!business || !refData) {
    return (
      <Stack gap="md">
        <Title order={2}>Settings</Title>
        <Skeleton height={200} />
      </Stack>
    )
  }

  const currencyOptions = refData.currencies.map((code) => ({
    value: code,
    label: CURRENCY_LABELS[code] ? `${code} — ${CURRENCY_LABELS[code]}` : code,
  }))

  const saveButton = (label: string) =>
    canWrite ? (
      <Button type="submit" mt="xs">
        {label}
      </Button>
    ) : (
      <Tooltip label="Owners and admins only">
        <Button disabled mt="xs">
          {label}
        </Button>
      </Tooltip>
    )

  return (
    <Stack gap="md" maw={560}>
      <Title order={2}>Settings</Title>
      <Tabs defaultValue="profile">
        <Tabs.List>
          <Tabs.Tab value="profile">Business Profile</Tabs.Tab>
          <Tabs.Tab value="widget">Website Widget</Tabs.Tab>
        </Tabs.List>

        <Tabs.Panel value="profile" pt="md">
          <form onSubmit={profileForm.onSubmit(handleProfileSubmit)}>
            <Stack gap="sm">
              <TextInput
                label="Business name"
                withAsterisk
                disabled={!canWrite}
                {...profileForm.getInputProps('name')}
              />
              <Textarea
                label="Description"
                autosize
                minRows={2}
                disabled={!canWrite}
                {...profileForm.getInputProps('description')}
              />
              <TextInput label="Address" disabled={!canWrite} {...profileForm.getInputProps('address')} />
              <TextInput label="Phone" disabled={!canWrite} {...profileForm.getInputProps('phone')} />
              <TextInput
                label="Email"
                placeholder="name@example.com"
                disabled={!canWrite}
                {...profileForm.getInputProps('email')}
              />
              <TextInput label="Website" disabled={!canWrite} {...profileForm.getInputProps('website')} />
              <Select
                label="Timezone"
                withAsterisk
                searchable
                data={refData.timezones}
                disabled={!canWrite}
                // Select-all-on-focus so typing to search replaces the
                // current value instead of appending after it (native
                // input.select() — the standard combobox convention).
                onFocus={(e) => e.currentTarget.select()}
                {...profileForm.getInputProps('timezone')}
              />
              <Select
                label="Currency"
                withAsterisk
                data={currencyOptions}
                disabled={!canWrite}
                {...profileForm.getInputProps('currency')}
              />
              {saveButton('Save changes')}
            </Stack>
          </form>
        </Tabs.Panel>

        <Tabs.Panel value="widget" pt="md">
          <Text c="dimmed" size="sm" mb="sm">
            Your business name (Profile tab) and this color are shown to your customers in the website chat widget.
          </Text>
          <form onSubmit={widgetForm.onSubmit(handleWidgetSubmit)}>
            <Stack gap="sm">
              <ColorInput
                label="Primary color"
                description="Used for the chat bubble, header, and your messages in the website widget"
                disabled={!canWrite}
                {...widgetForm.getInputProps('brand_color')}
              />
              <TextInput
                label="Logo URL"
                placeholder="https://example.com/logo.png"
                description="Optional — shown in the widget header"
                disabled={!canWrite}
                {...widgetForm.getInputProps('logo_url')}
              />
              {saveButton('Save changes')}
            </Stack>
          </form>
        </Tabs.Panel>
      </Tabs>
    </Stack>
  )
}
