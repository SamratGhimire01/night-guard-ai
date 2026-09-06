import { useEffect, useState } from 'react'
import { Alert, Button, CopyButton, Group, Paper, Skeleton, Stack, Text, Title } from '@mantine/core'
import { apiFetch } from '../../api/client'
import type { BusinessRead } from '../../api/types'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL as string
const WIDGET_ORIGIN = new URL(API_BASE_URL).origin

export default function WebsiteWidgetPage() {
  const [business, setBusiness] = useState<BusinessRead | null>(null)

  useEffect(() => {
    apiFetch<BusinessRead>('/business/me').then(setBusiness)
  }, [])

  if (!business) {
    return (
      <Stack gap="md">
        <Title order={2}>Website Widget</Title>
        <Skeleton height={300} />
      </Stack>
    )
  }

  const snippet = `<script src="${WIDGET_ORIGIN}/widget.js" data-business-id="${business.id}"></script>`
  const previewHtml = `<body style="margin:0;font-family:sans-serif">${snippet}</body>`

  return (
    <Stack gap="lg">
      <Title order={2}>Website Widget</Title>
      <Text c="dimmed" size="sm">
        Paste this one script tag into your website's HTML (just before <code>&lt;/body&gt;</code>) to add a real
        chat widget powered by your AI assistant — no other setup needed.
      </Text>

      <Paper withBorder p="md" radius="md">
        <Group justify="space-between" mb="xs">
          <Text fw={600} size="sm">
            Embed code
          </Text>
          <CopyButton value={snippet}>
            {({ copied, copy }) => (
              <Button size="compact-sm" color={copied ? 'teal' : 'blue'} onClick={copy}>
                {copied ? 'Copied!' : 'Copy code'}
              </Button>
            )}
          </CopyButton>
        </Group>
        <Paper bg="gray.9" c="gray.1" p="sm" radius="sm" style={{ fontFamily: 'monospace', fontSize: 13, overflowX: 'auto' }}>
          {snippet}
        </Paper>
      </Paper>

      <Stack gap="xs">
        <Text fw={600} size="sm">
          Live preview
        </Text>
        <Text c="dimmed" size="xs">
          This is the real widget, embedded with your real business ID and current branding — not a mockup. Click
          the bubble in the bottom-right corner of the box below.
        </Text>
        <Alert color="blue" variant="light">
          Business name: <strong>{business.name}</strong> · Primary color:{' '}
          <strong style={{ color: business.brand_color }}>{business.brand_color}</strong>
          {business.logo_url ? ' · Logo set' : ' · No logo set (Settings)'}
        </Alert>
        <Paper withBorder radius="md" style={{ position: 'relative', height: 420, overflow: 'hidden' }}>
          <iframe
            title="Website widget preview"
            srcDoc={previewHtml}
            sandbox="allow-scripts"
            style={{ width: '100%', height: '100%', border: 'none' }}
          />
        </Paper>
      </Stack>
    </Stack>
  )
}
