import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import {
  ActionIcon,
  Alert,
  Anchor,
  Button,
  Code,
  ColorInput,
  CopyButton,
  Group,
  List,
  NumberInput,
  Paper,
  SegmentedControl,
  SimpleGrid,
  Skeleton,
  Stack,
  Switch,
  Tabs,
  Text,
  Textarea,
  TextInput,
  Title,
  Tooltip,
  UnstyledButton,
} from '@mantine/core'
import { useDebouncedValue } from '@mantine/hooks'
import { notifications } from '@mantine/notifications'
import {
  IconCalendarCheck,
  IconCheck,
  IconCode,
  IconCopy,
  IconDeviceDesktop,
  IconDeviceMobile,
  IconHeadset,
  IconHelpCircle,
  IconMessageCircle,
  IconMessages,
  IconPalette,
  IconPhoto,
  IconPlus,
  IconSparkles,
  IconTrash,
} from '@tabler/icons-react'
import { Link } from 'react-router-dom'
import { useAuth } from '../../auth/AuthContext'
import { apiAssetUrl, apiFetch, ApiError } from '../../api/client'
import type { BusinessRead, LauncherIcon, WidgetSettings } from '../../api/types'
import PageHeader from '../../components/PageHeader'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL as string
const WIDGET_ORIGIN = new URL(API_BASE_URL, window.location.href).origin

const SWATCHES = ['#7E3BDB', '#2563EB', '#0891B2', '#059669', '#D97706', '#DC2626', '#DB2777', '#111827']

const LAUNCHER_ICONS: { value: LauncherIcon; label: string; icon: ReactNode }[] = [
  { value: 'chat', label: 'Chat', icon: <IconMessageCircle size={22} /> },
  { value: 'sparkles', label: 'AI sparkle', icon: <IconSparkles size={22} /> },
  { value: 'headset', label: 'Support', icon: <IconHeadset size={22} /> },
  { value: 'question', label: 'Help', icon: <IconHelpCircle size={22} /> },
  { value: 'calendar', label: 'Booking', icon: <IconCalendarCheck size={22} /> },
  { value: 'logo', label: 'Your logo', icon: <IconPhoto size={22} /> },
]

type Draft = WidgetSettings & { brand_color: string }

function attr(value: string) {
  return value.replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

/** A made-up web page with the real widget script on it, running on the settings being edited (not yet saved). */
function previewDoc(business: BusinessRead, draft: Draft) {
  const config = { ...draft, name: business.name, logo_url: apiAssetUrl(business.logo_url) }
  return `<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1">
<style>
body{margin:0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#f4f5f8;color:#1f2937}
.nav{display:flex;align-items:center;gap:10px;padding:16px 22px;background:#fff;border-bottom:1px solid #e5e7eb;font-weight:700}
.dot{width:26px;height:26px;border-radius:8px;background:${attr(draft.brand_color)}}
.hero{padding:34px 22px}.l{height:12px;border-radius:6px;background:#e3e5eb;margin:10px 0}
.card{height:90px;border-radius:14px;background:#fff;border:1px solid #e5e7eb}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:14px;padding:0 22px}
</style></head><body>
<div class="nav"><span class="dot"></span>${attr(business.name)}</div>
<div class="hero"><div class="l" style="width:55%;height:22px"></div><div class="l" style="width:80%"></div><div class="l" style="width:65%"></div></div>
<div class="grid"><div class="card"></div><div class="card"></div><div class="card"></div></div>
<script src="${WIDGET_ORIGIN}/widget.js" data-business-id="${business.id}" data-open="true" data-preview-config="${attr(JSON.stringify(config))}"></script>
</body></html>`
}

function Field({ label, description, children }: { label: string; description?: string; children: ReactNode }) {
  return (
    <Stack gap={6}>
      <div>
        <Text fw={600} size="sm">
          {label}
        </Text>
        {description && (
          <Text size="xs" c="dimmed">
            {description}
          </Text>
        )}
      </div>
      {children}
    </Stack>
  )
}

function InstallSteps({ snippet }: { snippet: string }) {
  const code = (
    <Paper p="md" radius="md" className="ng-code">
      <Group justify="space-between" align="flex-start" wrap="nowrap" gap="sm">
        <Code block style={{ background: 'transparent', flex: 1, minWidth: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>
          {snippet}
        </Code>
        <CopyButton value={snippet}>
          {({ copied, copy }) => (
            <Button size="sm" color={copied ? 'teal' : undefined} leftSection={copied ? <IconCheck size={16} /> : <IconCopy size={16} />} onClick={copy}>
              {copied ? 'Copied' : 'Copy'}
            </Button>
          )}
        </CopyButton>
      </Group>
    </Paper>
  )
  return (
    <Stack gap="md">
      <Text size="sm" c="dimmed">
        Add this one line to your website once. After that, every change you save here shows up on your site
        automatically. You never need to paste it again.
      </Text>
      {code}
      <Tabs defaultValue="html" variant="pills">
        <Tabs.List mb="sm">
          <Tabs.Tab value="html">Any website</Tabs.Tab>
          <Tabs.Tab value="wordpress">WordPress</Tabs.Tab>
          <Tabs.Tab value="wix">Wix</Tabs.Tab>
          <Tabs.Tab value="shopify">Shopify</Tabs.Tab>
        </Tabs.List>
        <Tabs.Panel value="html">
          <List type="ordered" size="sm" spacing={6}>
            <List.Item>Open your website's HTML (or ask whoever built your site).</List.Item>
            <List.Item>
              Paste the line just before the closing <Code>&lt;/body&gt;</Code> tag on every page.
            </List.Item>
            <List.Item>Save and publish. The chat button appears in the corner.</List.Item>
          </List>
        </Tabs.Panel>
        <Tabs.Panel value="wordpress">
          <List type="ordered" size="sm" spacing={6}>
            <List.Item>Install a free plugin such as "WPCode" (Insert Headers and Footers).</List.Item>
            <List.Item>Open its Footer section and paste the line.</List.Item>
            <List.Item>Save. The chat appears on every page.</List.Item>
          </List>
        </Tabs.Panel>
        <Tabs.Panel value="wix">
          <List type="ordered" size="sm" spacing={6}>
            <List.Item>Go to Settings, then Custom Code, then Add Custom Code.</List.Item>
            <List.Item>Paste the line, choose "All pages" and "Body - end".</List.Item>
            <List.Item>Apply and publish your site.</List.Item>
          </List>
        </Tabs.Panel>
        <Tabs.Panel value="shopify">
          <List type="ordered" size="sm" spacing={6}>
            <List.Item>Go to Online Store, then Themes, then Edit code.</List.Item>
            <List.Item>
              Open <Code>theme.liquid</Code> and paste the line just before <Code>&lt;/body&gt;</Code>.
            </List.Item>
            <List.Item>Save.</List.Item>
          </List>
        </Tabs.Panel>
      </Tabs>
    </Stack>
  )
}

export default function WebsiteWidgetPage() {
  const { role } = useAuth()
  const canWrite = role === 'owner' || role === 'admin'
  const [business, setBusiness] = useState<BusinessRead | null>(null)
  const [saved, setSaved] = useState<Draft | null>(null)
  const [draft, setDraft] = useState<Draft | null>(null)
  const [saving, setSaving] = useState(false)
  const [device, setDevice] = useState<'desktop' | 'phone'>('desktop')

  useEffect(() => {
    Promise.all([apiFetch<BusinessRead>('/business/me'), apiFetch<WidgetSettings>('/business/widget-settings')]).then(
      ([b, w]) => {
        const initial = { ...w, brand_color: b.brand_color }
        setBusiness(b)
        setSaved(initial)
        setDraft(initial)
      },
    )
  }, [])

  const [debouncedDraft] = useDebouncedValue(draft, 350)
  const doc = useMemo(
    () => (business && debouncedDraft ? previewDoc(business, debouncedDraft) : ''),
    [business, debouncedDraft],
  )

  // The preview reloads ~350ms after each edit. Whatever the page inside it does on load, typing must stay in the field
  // the owner is editing: remember that field, and take focus back if the reloaded preview grabbed it.
  const lastField = useRef<HTMLElement | null>(null)
  const previewFrame = useRef<HTMLIFrameElement>(null)
  const keepTypingFocus = () => {
    const field = lastField.current
    if (field && field.isConnected && document.activeElement === previewFrame.current) field.focus({ preventScroll: true })
  }

  if (!business || !draft || !saved) {
    return (
      <Stack gap="lg">
        <PageHeader title="Website chat" description="Design the chat that appears on your website, then add it with one line." />
        <SimpleGrid cols={{ base: 1, lg: 2 }}>
          <Skeleton height={520} radius="lg" />
          <Skeleton height={520} radius="lg" />
        </SimpleGrid>
      </Stack>
    )
  }

  const set = <K extends keyof Draft>(key: K, value: Draft[K]) => setDraft((d) => (d ? { ...d, [key]: value } : d))
  const dirty = JSON.stringify(draft) !== JSON.stringify(saved)
  const snippet = `<script src="${WIDGET_ORIGIN}/widget.js" data-business-id="${business.id}" async></script>`
  const hasLogo = !!business.logo_url

  async function save() {
    if (!draft || !saved) return
    setSaving(true)
    try {
      const { brand_color, ...settings } = draft
      const tasks: Promise<unknown>[] = [
        apiFetch<WidgetSettings>('/business/widget-settings', { method: 'PUT', body: JSON.stringify(settings) }),
      ]
      if (brand_color !== saved.brand_color) {
        tasks.push(apiFetch<BusinessRead>('/business/me', { method: 'PATCH', body: JSON.stringify({ brand_color }) }))
      }
      const [w] = (await Promise.all(tasks)) as [WidgetSettings]
      const next = { ...w, brand_color }
      setSaved(next)
      setDraft(next)
      notifications.show({ color: 'green', message: 'Saved. Your website chat is updated.' })
    } catch (err) {
      notifications.show({ color: 'red', message: err instanceof ApiError ? err.message : 'Could not save. Please try again.' })
    } finally {
      setSaving(false)
    }
  }

  const questions = draft.suggested_questions

  return (
    <Stack gap="lg">
      <PageHeader
        title="Website chat"
        description="Design the chat that appears on your website. Changes show in the preview straight away; save to publish them."
        actions={
          canWrite && (
            <Group gap="xs">
              {dirty && (
                <Button variant="default" onClick={() => setDraft(saved)} disabled={saving}>
                  Discard
                </Button>
              )}
              <Button onClick={save} loading={saving} disabled={!dirty}>
                {dirty ? 'Save and publish' : 'All changes saved'}
              </Button>
            </Group>
          )
        }
      />

      <div className="ng-widget-editor">
        <Paper
          p={{ base: 'md', sm: 'lg' }}
          className="ng-widget-controls"
          onFocusCapture={(e) => {
            if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) lastField.current = e.target
          }}
          onBlurCapture={(e) => {
            // Leaving for anywhere other than the preview (e.g. clicking a button) ends the "still typing" state.
            if (e.relatedTarget && e.relatedTarget !== previewFrame.current) lastField.current = null
          }}
        >
          <Tabs defaultValue="look">
            <Tabs.List mb="lg">
              <Tabs.Tab value="look" leftSection={<IconPalette size={17} />}>
                Look
              </Tabs.Tab>
              <Tabs.Tab value="messages" leftSection={<IconMessages size={17} />}>
                Messages
              </Tabs.Tab>
              <Tabs.Tab value="install" leftSection={<IconCode size={17} />}>
                Add to website
              </Tabs.Tab>
            </Tabs.List>

            <Tabs.Panel value="look">
              <Stack gap="xl">
                <Field label="Main colour" description="Used for the chat button, header and the customer's messages.">
                  <ColorInput
                    format="hex"
                    swatches={SWATCHES}
                    swatchesPerRow={8}
                    disabled={!canWrite}
                    value={draft.brand_color}
                    onChange={(v) => /^#[0-9a-f]{6}$/i.test(v) && set('brand_color', v)}
                  />
                </Field>

                <SimpleGrid cols={2} spacing="lg">
                  <Field label="Theme">
                    <SegmentedControl
                      fullWidth
                      disabled={!canWrite}
                      value={draft.theme}
                      onChange={(v) => set('theme', v as Draft['theme'])}
                      data={[
                        { value: 'light', label: 'Light' },
                        { value: 'dark', label: 'Dark' },
                      ]}
                    />
                  </Field>
                  <Field label="Button position">
                    <SegmentedControl
                      fullWidth
                      disabled={!canWrite}
                      value={draft.position}
                      onChange={(v) => set('position', v as Draft['position'])}
                      data={[
                        { value: 'left', label: 'Left' },
                        { value: 'right', label: 'Right' },
                      ]}
                    />
                  </Field>
                </SimpleGrid>

                <Field label="Chat button icon">
                  <SimpleGrid cols={{ base: 3, sm: 6 }} spacing="xs">
                    {LAUNCHER_ICONS.map((opt) => {
                      const unavailable = opt.value === 'logo' && !hasLogo
                      const tile = (
                        <UnstyledButton
                          key={opt.value}
                          className="ng-icon-choice"
                          data-active={draft.launcher_icon === opt.value || undefined}
                          disabled={!canWrite || unavailable}
                          onClick={() => set('launcher_icon', opt.value)}
                          aria-pressed={draft.launcher_icon === opt.value}
                        >
                          <span className="ng-icon-choice-dot" style={{ background: draft.brand_color }}>
                            {opt.icon}
                          </span>
                          <Text size="xs" fw={600}>
                            {opt.label}
                          </Text>
                        </UnstyledButton>
                      )
                      return unavailable ? (
                        <Tooltip key={opt.value} label="Upload a logo in Settings first">
                          <span>{tile}</span>
                        </Tooltip>
                      ) : (
                        tile
                      )
                    })}
                  </SimpleGrid>
                </Field>

                <TextInput
                  label="Text next to the button"
                  description="Optional. A short label such as 'Chat with us' or 'Book online'."
                  placeholder="No label"
                  maxLength={30}
                  disabled={!canWrite}
                  value={draft.launcher_label}
                  onChange={(e) => set('launcher_label', e.currentTarget.value)}
                />

                <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="lg">
                  <TextInput
                    label="Chat title"
                    placeholder={business.name}
                    maxLength={40}
                    disabled={!canWrite}
                    value={draft.display_name}
                    onChange={(e) => set('display_name', e.currentTarget.value)}
                  />
                  <TextInput
                    label="Line under the title"
                    placeholder="We reply in seconds"
                    maxLength={80}
                    disabled={!canWrite}
                    value={draft.subtitle}
                    onChange={(e) => set('subtitle', e.currentTarget.value)}
                  />
                </SimpleGrid>

                <Group gap="md" wrap="nowrap" align="center" className="ng-inline-note">
                  <Text size="sm" style={{ flex: 1 }}>
                    {hasLogo ? 'Your logo is used as the chat avatar.' : 'Add your logo so customers recognise you in the chat.'}
                  </Text>
                  <Anchor component={Link} to="/dashboard/settings" size="sm">
                    {hasLogo ? 'Change logo' : 'Upload logo'}
                  </Anchor>
                </Group>

                <Switch
                  label='Show "Powered by Night Guard AI"'
                  disabled={!canWrite}
                  checked={draft.show_branding}
                  onChange={(e) => set('show_branding', e.currentTarget.checked)}
                />
              </Stack>
            </Tabs.Panel>

            <Tabs.Panel value="messages">
              <Stack gap="xl">
                <Textarea
                  label="Welcome message"
                  description="The first thing visitors read when they open the chat."
                  placeholder="Hi there! How can we help you today?"
                  autosize
                  minRows={2}
                  maxLength={400}
                  disabled={!canWrite}
                  value={draft.welcome_message}
                  onChange={(e) => set('welcome_message', e.currentTarget.value)}
                />

                <Field
                  label="Suggested questions"
                  description="Up to 4 buttons visitors can tap instead of typing. Short questions work best."
                >
                  <Stack gap="xs">
                    {questions.map((q, i) => (
                      <Group key={i} gap="xs" wrap="nowrap">
                        <TextInput
                          style={{ flex: 1 }}
                          maxLength={80}
                          placeholder={['What are your opening hours?', 'How much does it cost?', 'Can I book for tomorrow?', 'Where are you located?'][i]}
                          aria-label={`Suggested question ${i + 1}`}
                          disabled={!canWrite}
                          value={q}
                          onChange={(e) => {
                            const next = [...questions]
                            next[i] = e.currentTarget.value
                            set('suggested_questions', next)
                          }}
                        />
                        <ActionIcon
                          color="red"
                          aria-label={`Remove suggested question ${i + 1}`}
                          disabled={!canWrite}
                          onClick={() => set('suggested_questions', questions.filter((_, j) => j !== i))}
                        >
                          <IconTrash size={18} />
                        </ActionIcon>
                      </Group>
                    ))}
                    {questions.length < 4 && (
                      <Button
                        variant="default"
                        leftSection={<IconPlus size={17} />}
                        disabled={!canWrite}
                        onClick={() => set('suggested_questions', [...questions, ''])}
                        style={{ alignSelf: 'flex-start' }}
                      >
                        Add a question
                      </Button>
                    )}
                  </Stack>
                </Field>

                <TextInput
                  label="Message box hint"
                  placeholder="Type your message..."
                  maxLength={60}
                  disabled={!canWrite}
                  value={draft.input_placeholder}
                  onChange={(e) => set('input_placeholder', e.currentTarget.value)}
                />

                <Field label="Greeting bubble" description="Shows your welcome message above the chat button, once per visit.">
                  <Group gap="lg" align="flex-end" wrap="wrap">
                    <Switch
                      label="Show greeting bubble"
                      disabled={!canWrite}
                      checked={draft.show_popup}
                      onChange={(e) => set('show_popup', e.currentTarget.checked)}
                    />
                    {draft.show_popup && (
                      <NumberInput
                        label="Delay (seconds)"
                        w={160}
                        min={0}
                        max={60}
                        disabled={!canWrite}
                        value={draft.popup_delay_seconds}
                        onChange={(v) => set('popup_delay_seconds', Math.max(0, Math.min(60, Number(v) || 0)))}
                      />
                    )}
                  </Group>
                </Field>
              </Stack>
            </Tabs.Panel>

            <Tabs.Panel value="install">
              <InstallSteps snippet={snippet} />
            </Tabs.Panel>
          </Tabs>
          {!canWrite && (
            <Alert mt="lg" color="gray">
              Only owners and admins can change the website chat.
            </Alert>
          )}
        </Paper>

        <div className="ng-widget-preview-col">
          <Group justify="space-between" mb="sm">
            <Title order={4}>Live preview</Title>
            <SegmentedControl
              size="xs"
              value={device}
              onChange={(v) => setDevice(v as 'desktop' | 'phone')}
              data={[
                {
                  value: 'desktop',
                  label: (
                    <Group gap={6} wrap="nowrap">
                      <IconDeviceDesktop size={16} /> Desktop
                    </Group>
                  ),
                },
                {
                  value: 'phone',
                  label: (
                    <Group gap={6} wrap="nowrap">
                      <IconDeviceMobile size={16} /> Phone
                    </Group>
                  ),
                },
              ]}
            />
          </Group>
          <div className="ng-preview-frame" data-device={device}>
            {/* The real widget script, running on the unsaved settings. allow-forms lets the message box submit, so
                you can chat with your assistant here; there is no allow-same-origin, so the page stays sandboxed. */}
            <iframe
              ref={previewFrame}
              title="Website chat preview"
              srcDoc={doc}
              sandbox="allow-scripts allow-forms"
              onLoad={keepTypingFocus}
            />
          </div>
          <Text size="xs" c="dimmed" mt="xs" ta="center">
            This chat is live: messages you send here go to your assistant and appear in your Inbox.
          </Text>
        </div>
      </div>
    </Stack>
  )
}
