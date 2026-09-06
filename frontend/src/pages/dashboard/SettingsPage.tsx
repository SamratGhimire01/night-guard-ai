import { useEffect, useState } from 'react'
import { Button, ColorInput, Skeleton, Stack, Text, TextInput, Title, Tooltip } from '@mantine/core'
import { useForm } from '@mantine/form'
import { notifications } from '@mantine/notifications'
import { useAuth } from '../../auth/AuthContext'
import { apiFetch, ApiError } from '../../api/client'
import type { BusinessRead, BusinessUpdate } from '../../api/types'

export default function SettingsPage() {
  const { role } = useAuth()
  const canWrite = role === 'owner' || role === 'admin'

  const [business, setBusiness] = useState<BusinessRead | null>(null)

  useEffect(() => {
    apiFetch<BusinessRead>('/business/me').then(setBusiness)
  }, [])

  const form = useForm<Pick<BusinessUpdate, 'brand_color' | 'logo_url'>>({
    initialValues: { brand_color: '#2563eb', logo_url: '' },
  })

  useEffect(() => {
    if (business) form.setValues({ brand_color: business.brand_color, logo_url: business.logo_url ?? '' })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [business])

  async function handleSubmit(values: Pick<BusinessUpdate, 'brand_color' | 'logo_url'>) {
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

  if (!business) {
    return (
      <Stack gap="md">
        <Title order={2}>Settings</Title>
        <Skeleton height={200} />
      </Stack>
    )
  }

  return (
    <Stack gap="md" maw={480}>
      <Title order={2}>Settings</Title>
      <Text c="dimmed" size="sm">
        This name and color are shown to your customers in the website chat widget (Website Widget section).
      </Text>
      <form onSubmit={form.onSubmit(handleSubmit)}>
        <Stack gap="sm">
          <TextInput label="Business name" value={business.name} disabled description="Edit under a future phase" />
          <ColorInput
            label="Primary color"
            description="Used for the chat bubble, header, and your messages in the website widget"
            disabled={!canWrite}
            {...form.getInputProps('brand_color')}
          />
          <TextInput
            label="Logo URL"
            placeholder="https://example.com/logo.png"
            description="Optional — shown in the widget header"
            disabled={!canWrite}
            {...form.getInputProps('logo_url')}
          />
          {canWrite ? (
            <Button type="submit" mt="xs">
              Save changes
            </Button>
          ) : (
            <Tooltip label="Owners and admins only">
              <Button disabled mt="xs">
                Save changes
              </Button>
            </Tooltip>
          )}
        </Stack>
      </form>
    </Stack>
  )
}
