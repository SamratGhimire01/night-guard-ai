import { useEffect, useState } from 'react'
import { Alert, Anchor, Badge, Button, Group, Paper, PasswordInput, Skeleton, Stack, Text, TextInput, Title } from '@mantine/core'
import { useForm } from '@mantine/form'
import { notifications } from '@mantine/notifications'
import { useAuth } from '../../auth/AuthContext'
import { apiFetch, ApiError } from '../../api/client'
import type { ChannelType, IntegrationRead, IntegrationTestResult } from '../../api/types'

interface FieldSpec {
  key: string
  label: string
  secret: boolean
}

interface ChannelSpec {
  type: ChannelType
  title: string
  fields: FieldSpec[]
  helpText: string
  docsUrl: string
  testable: boolean
}

const CHANNELS: ChannelSpec[] = [
  {
    type: 'whatsapp',
    title: 'WhatsApp',
    fields: [
      { key: 'phone_number_id', label: 'Phone Number ID', secret: false },
      { key: 'access_token', label: 'Access Token', secret: true },
    ],
    helpText: 'Find these in Meta’s WhatsApp Business Platform dashboard, under your app’s API Setup page.',
    docsUrl: 'https://developers.facebook.com/docs/whatsapp/cloud-api/get-started',
    testable: true,
  },
  {
    type: 'messenger',
    title: 'Messenger',
    fields: [
      { key: 'page_id', label: 'Page ID', secret: false },
      { key: 'page_access_token', label: 'Page Access Token', secret: true },
    ],
    helpText: 'Find these in Meta’s Messenger Platform dashboard, under your app’s Messenger settings.',
    docsUrl: 'https://developers.facebook.com/docs/messenger-platform/get-started',
    testable: true,
  },
  {
    type: 'instagram',
    title: 'Instagram',
    fields: [
      { key: 'ig_account_id', label: 'Instagram Account ID', secret: false },
      { key: 'access_token', label: 'Access Token', secret: true },
    ],
    helpText: 'Find these in Meta’s Instagram Messaging dashboard, under your app’s Instagram settings.',
    docsUrl: 'https://developers.facebook.com/docs/messenger-platform/instagram',
    testable: true,
  },
]

function ChannelSection({ spec, integration, onSaved }: { spec: ChannelSpec; integration: IntegrationRead | undefined; onSaved: () => void }) {
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const connected = integration?.enabled ?? false

  const initialValues = Object.fromEntries(
    spec.fields.map((f) => [f.key, f.secret ? '' : integration?.config?.[f.key] ?? '']),
  )
  const form = useForm({ initialValues })

  async function handleSave(values: Record<string, string>) {
    setSaving(true)
    try {
      await apiFetch(`/integrations`, {
        method: 'POST',
        body: JSON.stringify({ type: spec.type, config: values, enabled: true }),
      })
      notifications.show({ message: `${spec.title} credentials saved.`, color: 'green' })
      // Secret fields go blank (never redisplayed); non-secret fields (e.g. a
      // phone/page/account id) stay visible since they're not sensitive.
      form.setValues(Object.fromEntries(spec.fields.map((f) => [f.key, f.secret ? '' : values[f.key]])))
      onSaved()
    } catch (err) {
      notifications.show({ message: err instanceof ApiError ? err.message : 'Could not save credentials.', color: 'red' })
    } finally {
      setSaving(false)
    }
  }

  async function handleTest() {
    setTesting(true)
    try {
      const result = await apiFetch<IntegrationTestResult>(`/integrations/${spec.type}/test-connection`, { method: 'POST' })
      notifications.show({ message: result.detail, color: result.ok ? 'green' : 'red' })
    } catch (err) {
      notifications.show({ message: err instanceof ApiError ? err.message : 'Test connection failed.', color: 'red' })
    } finally {
      setTesting(false)
    }
  }

  return (
    <Paper withBorder p="md" radius="md">
      <Stack gap="sm">
        <Group justify="space-between">
          <Title order={4}>{spec.title}</Title>
          <Badge color={connected ? 'green' : 'gray'} variant="light">
            {connected ? 'Connected' : 'Not connected'}
          </Badge>
        </Group>

        <Text size="sm" c="dimmed">
          {spec.helpText}{' '}
          <Anchor href={spec.docsUrl} target="_blank" rel="noreferrer" size="sm">
            Meta’s docs
          </Anchor>
          .
        </Text>

        <form onSubmit={form.onSubmit(handleSave)}>
          <Stack gap="sm">
            {spec.fields.map((f) =>
              f.secret ? (
                <PasswordInput
                  key={f.key}
                  label={f.label}
                  placeholder={connected ? 'Saved — enter a new value to replace it' : ''}
                  {...form.getInputProps(f.key)}
                />
              ) : (
                <TextInput key={f.key} label={f.label} {...form.getInputProps(f.key)} />
              ),
            )}
            <Group>
              <Button type="submit" loading={saving}>
                Save
              </Button>
              {spec.testable && (
                <Button variant="light" loading={testing} disabled={!connected} onClick={handleTest}>
                  Test connection
                </Button>
              )}
            </Group>
          </Stack>
        </form>
      </Stack>
    </Paper>
  )
}

export default function ChannelsPage() {
  const { role } = useAuth()
  const canAccess = role === 'owner' || role === 'admin'

  const [integrations, setIntegrations] = useState<IntegrationRead[] | null>(null)

  function load() {
    apiFetch<IntegrationRead[]>('/integrations').then(setIntegrations)
  }

  useEffect(() => {
    if (canAccess) load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [canAccess])

  if (!canAccess) {
    return (
      <Alert color="red" title="Not authorized">
        Only an owner or admin can view or manage channel connections.
      </Alert>
    )
  }

  return (
    <Stack gap="md" maw={640}>
      <div>
        <Title order={2}>Channels</Title>
        <Text c="dimmed" size="sm">
          Connect WhatsApp, Messenger, and Instagram using credentials you’ve already obtained from Meta. This page
          never asks for app secrets or verify tokens — those are platform-level settings, not something you enter
          here. Once saved, a credential is write-only: it’s never shown back to you.
        </Text>
      </div>

      {integrations === null ? (
        <Stack gap="md">
          <Skeleton height={220} />
          <Skeleton height={220} />
          <Skeleton height={220} />
        </Stack>
      ) : (
        CHANNELS.map((spec) => (
          <ChannelSection
            key={spec.type}
            spec={spec}
            integration={integrations.find((i) => i.type === spec.type)}
            onSaved={load}
          />
        ))
      )}
    </Stack>
  )
}
