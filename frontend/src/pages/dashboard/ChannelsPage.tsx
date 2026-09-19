import { useEffect, useState } from 'react'
import { Alert, Anchor, Badge, Button, Divider, Group, Paper, PasswordInput, Skeleton, Stack, Text, TextInput, Title } from '@mantine/core'
import { useForm } from '@mantine/form'
import { notifications } from '@mantine/notifications'
import { useAuth } from '../../auth/AuthContext'
import { apiFetch, ApiError } from '../../api/client'
import type { ChannelType, IntegrationRead, IntegrationTestResult, WhatsAppEmbeddedSignupConfig } from '../../api/types'

// Meta's JS SDK (loaded lazily, only if/when the WhatsApp section's self-serve
// button is used — not injected globally in index.html). Minimal ambient type
// for just the two calls this page makes; see WhatsAppEmbeddedSignupButton.
declare global {
  interface Window {
    FB?: {
      init: (params: { appId: string; autoLogAppEvents?: boolean; xfbml?: boolean; version: string }) => void
      login: (
        callback: (response: { authResponse?: { code?: string } }) => void,
        params: {
          config_id: string
          response_type: string
          override_default_response_type: boolean
          extras?: Record<string, unknown>
        },
      ) => void
    }
    fbAsyncInit?: () => void
  }
}

function loadFacebookSdk(appId: string, apiVersion: string): Promise<void> {
  return new Promise((resolve) => {
    if (window.FB) {
      resolve()
      return
    }
    window.fbAsyncInit = () => {
      window.FB!.init({ appId, autoLogAppEvents: true, xfbml: true, version: apiVersion })
      resolve()
    }
    if (document.getElementById('facebook-jssdk')) return
    const script = document.createElement('script')
    script.id = 'facebook-jssdk'
    script.src = 'https://connect.facebook.net/en_US/sdk.js'
    script.async = true
    script.defer = true
    document.body.appendChild(script)
  })
}

/** A NEW, separate self-serve option for WhatsApp only — real Meta Embedded
 * Signup via FB.login(), alongside (never replacing) the manual Phone Number
 * ID / Access Token fields below. Renders nothing but an explanatory note if
 * the platform hasn't configured WHATSAPP_EMBEDDED_SIGNUP_APP_ID/_CONFIG_ID. */
function WhatsAppEmbeddedSignupButton({ onConnected }: { onConnected: () => void }) {
  const [config, setConfig] = useState<WhatsAppEmbeddedSignupConfig | null>(null)
  const [connecting, setConnecting] = useState(false)

  useEffect(() => {
    apiFetch<WhatsAppEmbeddedSignupConfig>('/integrations/whatsapp/embedded-signup/config').then(setConfig)
  }, [])

  async function handleConnect() {
    if (!config?.configured) return
    setConnecting(true)

    let waba_id: string | undefined
    let phone_number_id: string | undefined
    function messageListener(event: MessageEvent) {
      if (event.origin !== 'https://www.facebook.com' && event.origin !== 'https://web.facebook.com') return
      try {
        const data = JSON.parse(event.data)
        if (data.type === 'WA_EMBEDDED_SIGNUP' && data.event === 'FINISH') {
          waba_id = data.data?.waba_id
          phone_number_id = data.data?.phone_number_id
        }
      } catch {
        // A non-JSON postMessage from an unrelated source — ignored.
      }
    }
    window.addEventListener('message', messageListener)

    try {
      await loadFacebookSdk(config.app_id, config.api_version)
      const response = await new Promise<{ authResponse?: { code?: string } }>((resolve) => {
        window.FB!.login(resolve, {
          config_id: config.config_id,
          response_type: 'code',
          override_default_response_type: true,
          extras: { setup: {} },
        })
      })
      const code = response.authResponse?.code
      if (!code) {
        notifications.show({ message: 'WhatsApp connect was cancelled or did not complete.', color: 'yellow' })
        return
      }
      // The postMessage carrying waba_id/phone_number_id can arrive slightly
      // after FB.login's own callback — give it a brief moment if needed.
      if (!waba_id || !phone_number_id) {
        await new Promise((r) => setTimeout(r, 1500))
      }
      if (!waba_id || !phone_number_id) {
        notifications.show({ message: 'WhatsApp did not return the expected account details. Please try again.', color: 'red' })
        return
      }
      await apiFetch('/integrations/whatsapp/embedded-signup', {
        method: 'POST',
        body: JSON.stringify({ code, waba_id, phone_number_id }),
      })
      notifications.show({ message: 'WhatsApp connected.', color: 'green' })
      onConnected()
    } catch (err) {
      notifications.show({ message: err instanceof ApiError ? err.message : 'WhatsApp connect failed.', color: 'red' })
    } finally {
      window.removeEventListener('message', messageListener)
      setConnecting(false)
    }
  }

  if (config && !config.configured) {
    return (
      <Text size="sm" c="dimmed">
        Self-serve connect isn't set up yet — use the manual fields below instead.
      </Text>
    )
  }

  return (
    <Button variant="outline" loading={connecting} disabled={!config} onClick={handleConnect}>
      Connect WhatsApp (self-serve)
    </Button>
  )
}

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

        {spec.type === 'whatsapp' && (
          <>
            <WhatsAppEmbeddedSignupButton onConnected={onSaved} />
            <Divider label="or enter credentials manually" labelPosition="center" />
          </>
        )}

        <form onSubmit={form.onSubmit(handleSave)}>
          <Stack gap="sm">
            {spec.fields.map((f) =>
              f.secret ? (
                <PasswordInput
                  key={f.key}
                  label={f.label}
                  placeholder={connected ? 'Saved — enter a new value to replace it' : ''}
                  // Real, live-caught bug (see PHASE_STATUS.md): the browser's
                  // credential manager was auto-filling this Meta API token
                  // field with the dashboard's own saved LOGIN password,
                  // since a bare PasswordInput reads as a login field to
                  // autofill heuristics. autoComplete="new-password" is the
                  // modern, reliable way to opt a password-type input out of
                  // that (autoComplete="off" is unreliably honored by
                  // browsers specifically for password fields).
                  autoComplete="new-password"
                  {...form.getInputProps(f.key)}
                />
              ) : (
                // Same bug, same root cause, for the non-secret id fields
                // (Phone Number ID / Page ID / Instagram Account ID) — these
                // aren't password-type, so autoComplete="off" (reliable for
                // plain text inputs) is enough.
                <TextInput key={f.key} label={f.label} autoComplete="off" {...form.getInputProps(f.key)} />
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
