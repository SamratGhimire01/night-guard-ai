import { useEffect, useRef, useState, type ReactNode } from 'react'
import { useSearchParams } from 'react-router-dom'
import {
  Badge,
  Button,
  FileButton,
  Group,
  List,
  NumberInput,
  Paper,
  Radio,
  SegmentedControl,
  Select,
  SimpleGrid,
  Skeleton,
  Stack,
  Switch,
  Tabs,
  Text,
  Textarea,
  TextInput,
  Title,
} from '@mantine/core'
import { useForm } from '@mantine/form'
import { notifications } from '@mantine/notifications'
import {
  IconBuildingStore,
  IconCalendarCheck,
  IconCrown,
  IconPhotoUp,
  IconRobot,
  IconTrash,
  IconUsers,
} from '@tabler/icons-react'
import { useAuth } from '../../auth/AuthContext'
import { apiAssetUrl, apiFetch, ApiError } from '../../api/client'
import type {
  BusinessReferenceData,
  BusinessRead,
  BusinessUpdate,
  ContentScope,
  EmojiPolicy,
  Formality,
  LanguageMode,
  PlanRead,
  UpgradeRequestResult,
} from '../../api/types'
import PageHeader from '../../components/PageHeader'
import AccountTab from './settings/AccountTab'

const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/
const URL_RE = /^https?:\/\/[^\s.]+\.[^\s]+$/i

// Friendly labels for the currency dropdown — cosmetic only. The option VALUES (and the timezone list entirely) come
// from GET /business/reference-data, i.e. the backend's own validated sets, so the two can never drift apart.
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

// Values match the backend's style-example categories (data/style_exemplars), so picking one also gives the assistant
// tone examples written for that kind of business. Anything else still works; it just uses the shared examples.
const BUSINESS_TYPES = [
  { value: 'dental', label: 'Dental clinic' },
  { value: 'clinic', label: 'Medical clinic' },
  { value: 'salon', label: 'Salon, spa or beauty' },
  { value: 'trekking', label: 'Trekking, tours or travel' },
  { value: 'study_abroad', label: 'Education or study-abroad consultancy' },
  { value: 'organic_food', label: 'Food, grocery or restaurant' },
  { value: 'other', label: 'Something else' },
]

const LOGO_TYPES = ['image/png', 'image/jpeg', 'image/webp']
const MAX_LOGO_BYTES = 1024 * 1024

type ProfileValues = {
  name: string
  business_type: string
  description: string
  phone: string
  email: string
  website: string
  address: string
  timezone: string
  currency: string
}

type AssistantValues = {
  persona_name: string
  formality: Formality
  emoji_policy: EmojiPolicy
  sign_off: string
  language_mode: LanguageMode
  content_scope: ContentScope
}

type BookingValues = {
  booking_enabled: boolean
  reminder_enabled: boolean
  reminder_minutes_before: number
  owner_alerts_enabled: boolean
}

const REMINDER_PRESETS = [
  { value: '60', label: '1 hour before' },
  { value: '120', label: '2 hours before' },
  { value: '1440', label: '1 day before' },
  { value: 'custom', label: 'Custom' },
]

function profileFrom(b: BusinessRead): ProfileValues {
  return {
    name: b.name,
    business_type: b.business_type ?? '',
    description: b.description ?? '',
    phone: b.phone ?? '',
    email: b.email ?? '',
    website: b.website ?? '',
    address: b.address ?? '',
    timezone: b.timezone,
    currency: b.currency,
  }
}

function assistantFrom(b: BusinessRead): AssistantValues {
  return {
    persona_name: b.persona_name ?? '',
    formality: b.formality,
    emoji_policy: b.emoji_policy,
    sign_off: b.sign_off ?? '',
    language_mode: b.language_mode,
    content_scope: b.content_scope,
  }
}

function bookingFrom(b: BusinessRead): BookingValues {
  return {
    booking_enabled: b.booking_enabled,
    reminder_enabled: b.reminder_enabled,
    reminder_minutes_before: b.reminder_minutes_before,
    owner_alerts_enabled: b.owner_alerts_enabled,
  }
}

/** A titled group of fields inside a settings tab. */
function Section({ title, description, children }: { title: string; description?: string; children: ReactNode }) {
  return (
    <Paper p={{ base: 'md', sm: 'xl' }}>
      <Stack gap="lg">
        <div>
          <Title order={3}>{title}</Title>
          {description && (
            <Text c="dimmed" size="sm" mt={4} maw={640}>
              {description}
            </Text>
          )}
        </div>
        {children}
      </Stack>
    </Paper>
  )
}

/** Appears only when the tab has unsaved changes, so it is always clear whether anything still needs saving. */
function SaveBar({ dirty, saving, onDiscard, canWrite }: { dirty: boolean; saving: boolean; onDiscard: () => void; canWrite: boolean }) {
  if (!canWrite) {
    return (
      <Text size="sm" c="dimmed">
        Only owners and admins can change these settings.
      </Text>
    )
  }
  if (!dirty) return null
  return (
    <Paper className="ng-savebar" p="sm" radius="xl">
      <Group justify="space-between" wrap="wrap" gap="sm">
        <Text fw={600} size="sm" pl="xs">
          You have unsaved changes
        </Text>
        <Group gap="xs">
          <Button variant="default" onClick={onDiscard} disabled={saving}>
            Discard
          </Button>
          <Button type="submit" loading={saving}>
            Save changes
          </Button>
        </Group>
      </Group>
    </Paper>
  )
}

function LogoUploader({
  business,
  canWrite,
  onChange,
}: {
  business: BusinessRead
  canWrite: boolean
  onChange: (b: BusinessRead) => void
}) {
  const [busy, setBusy] = useState(false)
  const [dragging, setDragging] = useState(false)
  const resetRef = useRef<() => void>(null)
  const src = apiAssetUrl(business.logo_url)

  async function upload(file: File | null) {
    resetRef.current?.()
    if (!file) return
    if (!LOGO_TYPES.includes(file.type)) {
      notifications.show({ color: 'red', message: 'Please choose a PNG, JPG or WebP image.' })
      return
    }
    if (file.size > MAX_LOGO_BYTES) {
      notifications.show({ color: 'red', message: 'That image is larger than 1 MB. Please choose a smaller one.' })
      return
    }
    const body = new FormData()
    body.append('file', file)
    setBusy(true)
    try {
      onChange(await apiFetch<BusinessRead>('/business/logo', { method: 'POST', body }))
      notifications.show({ color: 'green', message: 'Logo updated. It now shows in your website chat.' })
    } catch (err) {
      notifications.show({ color: 'red', message: err instanceof ApiError ? err.message : 'Upload failed.' })
    } finally {
      setBusy(false)
    }
  }

  async function remove() {
    setBusy(true)
    try {
      onChange(await apiFetch<BusinessRead>('/business/logo', { method: 'DELETE' }))
      notifications.show({ message: 'Logo removed.' })
    } catch (err) {
      notifications.show({ color: 'red', message: err instanceof ApiError ? err.message : 'Could not remove the logo.' })
    } finally {
      setBusy(false)
    }
  }

  const initials = business.name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase())
    .join('')

  return (
    <Group
      gap="lg"
      align="center"
      wrap="wrap"
      className="ng-logo-drop"
      data-dragging={dragging || undefined}
      onDragOver={(e) => {
        if (!canWrite) return
        e.preventDefault()
        setDragging(true)
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={(e) => {
        if (!canWrite) return
        e.preventDefault()
        setDragging(false)
        upload(e.dataTransfer.files?.[0] ?? null)
      }}
    >
      <div className="ng-logo-preview">
        {src ? <img src={src} alt={`${business.name} logo`} /> : <span>{initials || '?'}</span>}
      </div>
      <Stack gap={6} style={{ flex: '1 1 220px' }}>
        <Text fw={700}>Business logo</Text>
        <Text size="sm" c="dimmed">
          Shown in your website chat and on your dashboard. Square images look best. PNG, JPG or WebP, up to 1 MB. You
          can also drag an image here.
        </Text>
        <Group gap="xs" mt={4}>
          <FileButton resetRef={resetRef} onChange={upload} accept={LOGO_TYPES.join(',')} disabled={!canWrite}>
            {(props) => (
              <Button {...props} leftSection={<IconPhotoUp size={18} />} loading={busy} disabled={!canWrite}>
                {src ? 'Change logo' : 'Upload logo'}
              </Button>
            )}
          </FileButton>
          {src && (
            <Button variant="default" leftSection={<IconTrash size={17} />} onClick={remove} disabled={!canWrite || busy}>
              Remove
            </Button>
          )}
        </Group>
      </Stack>
    </Group>
  )
}

export default function SettingsPage() {
  const { role } = useAuth()
  const canWrite = role === 'owner' || role === 'admin'

  const [business, setBusiness] = useState<BusinessRead | null>(null)
  const [refData, setRefData] = useState<BusinessReferenceData | null>(null)
  const [plan, setPlan] = useState<PlanRead | null>(null)
  const [saving, setSaving] = useState<string | null>(null)
  const [params, setParams] = useSearchParams()
  const tab = ['profile', 'assistant', 'bookings', 'plan', 'account'].includes(params.get('tab') ?? '') ? params.get('tab')! : 'profile'
  const [requesting, setRequesting] = useState(false)

  useEffect(() => {
    apiFetch<BusinessRead>('/business/me').then(setBusiness)
    apiFetch<BusinessReferenceData>('/business/reference-data').then(setRefData)
    apiFetch<PlanRead>('/business/plan').then(setPlan)
  }, [])

  const profileForm = useForm<ProfileValues>({
    initialValues: profileFrom({ name: '', timezone: '', currency: '' } as BusinessRead),
    validate: {
      name: (v) => (v.trim() ? null : 'Please enter your business name.'),
      email: (v) => (!v || EMAIL_RE.test(v) ? null : 'Enter a full email address, like name@example.com.'),
      website: (v) => (!v || URL_RE.test(v) ? null : 'Enter the full address, starting with https://'),
      timezone: (v) => (v ? null : 'Choose your time zone.'),
      currency: (v) => (v ? null : 'Choose your currency.'),
    },
  })
  const assistantForm = useForm<AssistantValues>({ initialValues: assistantFrom({} as BusinessRead) })
  const bookingForm = useForm<BookingValues>({
    initialValues: { booking_enabled: true, reminder_enabled: false, reminder_minutes_before: 60, owner_alerts_enabled: true },
    validate: {
      reminder_minutes_before: (v, values) =>
        !values.reminder_enabled || (v >= 5 && v <= 1440) ? null : 'Choose between 5 minutes and 1 day (1440 minutes).',
    },
  })

  // Load (and re-load after a save) the saved values as the forms' clean baseline.
  function syncForms(b: BusinessRead) {
    const baseline = <T extends object>(form: { setInitialValues: (v: T) => void; setValues: (v: T) => void; resetDirty: (v: T) => void }, values: T) => {
      form.setInitialValues(values)
      form.setValues(values)
      form.resetDirty(values)
    }
    baseline(profileForm, profileFrom(b))
    baseline(assistantForm, assistantFrom(b))
    baseline(bookingForm, bookingFrom(b))
  }

  useEffect(() => {
    if (business) syncForms(business)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [business])

  async function save(section: string, body: BusinessUpdate, message: string) {
    setSaving(section)
    try {
      const updated = await apiFetch<BusinessRead>('/business/me', { method: 'PATCH', body: JSON.stringify(body) })
      setBusiness(updated)
      notifications.show({ color: 'green', message })
    } catch (err) {
      notifications.show({ color: 'red', message: err instanceof ApiError ? err.message : 'Could not save. Please try again.' })
    } finally {
      setSaving(null)
    }
  }

  async function requestUpgrade() {
    setRequesting(true)
    try {
      const result = await apiFetch<UpgradeRequestResult>('/business/plan/upgrade-request', { method: 'POST' })
      setBusiness((b) => (b ? { ...b, upgrade_requested_at: result.requested_at } : b))
      notifications.show({
        color: 'green',
        message: result.team_notified
          ? 'Request sent. Our team will contact you soon.'
          : 'Request saved. Our team will see it and contact you.',
      })
    } catch (err) {
      notifications.show({ color: 'red', message: err instanceof ApiError ? err.message : 'Could not send the request. Please try again.' })
    } finally {
      setRequesting(false)
    }
  }

  if (!business || !refData) {
    return (
      <Stack gap="lg">
        <PageHeader title="Settings" description="Your business details, how your assistant talks, and your plan." />
        <Skeleton height={48} radius="xl" maw={640} />
        <Skeleton height={420} radius="lg" />
      </Stack>
    )
  }

  const currencyOptions = refData.currencies.map((code) => ({
    value: code,
    label: CURRENCY_LABELS[code] ? `${code} — ${CURRENCY_LABELS[code]}` : code,
  }))
  const typeOptions =
    business.business_type && !BUSINESS_TYPES.some((t) => t.value === business.business_type)
      ? [...BUSINESS_TYPES, { value: business.business_type, label: business.business_type }]
      : BUSINESS_TYPES
  const reminderPreset = REMINDER_PRESETS.some((p) => p.value === String(bookingForm.values.reminder_minutes_before))
    ? String(bookingForm.values.reminder_minutes_before)
    : 'custom'
  const blank = (v: string) => v.trim() || null

  return (
    <Stack gap="lg">
      <PageHeader title="Settings" description="Your business details, how your assistant talks, and your plan." />

      <Tabs value={tab} onChange={(v) => setParams(v && v !== 'profile' ? { tab: v } : {}, { replace: true })} keepMounted={false}>
        <Tabs.List mb="lg">
          <Tabs.Tab value="profile" leftSection={<IconBuildingStore size={18} />}>
            Business profile
          </Tabs.Tab>
          <Tabs.Tab value="assistant" leftSection={<IconRobot size={18} />}>
            AI assistant
          </Tabs.Tab>
          <Tabs.Tab value="bookings" leftSection={<IconCalendarCheck size={18} />}>
            Bookings &amp; reminders
          </Tabs.Tab>
          <Tabs.Tab value="plan" leftSection={<IconCrown size={18} />}>
            Plan
          </Tabs.Tab>
          <Tabs.Tab value="account" leftSection={<IconUsers size={18} />}>
            Account &amp; team
          </Tabs.Tab>
        </Tabs.List>

        <Tabs.Panel value="profile">
          <form
            onSubmit={profileForm.onSubmit((v) =>
              save(
                'profile',
                {
                  name: v.name.trim(),
                  business_type: blank(v.business_type),
                  description: blank(v.description),
                  phone: blank(v.phone),
                  email: blank(v.email),
                  website: blank(v.website),
                  address: blank(v.address),
                  timezone: v.timezone,
                  currency: v.currency,
                },
                'Business profile saved.',
              ),
            )}
          >
            <Stack gap="lg">
              <Section title="Brand" description="How your business appears to customers in chat, emails and receipts.">
                <LogoUploader business={business} canWrite={canWrite} onChange={setBusiness} />
                <SimpleGrid cols={{ base: 1, md: 2 }} spacing="lg">
                  <TextInput label="Business name" withAsterisk disabled={!canWrite} {...profileForm.getInputProps('name')} />
                  <Select
                    label="Type of business"
                    description="Helps the assistant use the right words for your industry."
                    placeholder="Choose one"
                    data={typeOptions}
                    clearable
                    disabled={!canWrite}
                    {...profileForm.getInputProps('business_type')}
                    value={profileForm.values.business_type || null}
                    onChange={(v) => profileForm.setFieldValue('business_type', v ?? '')}
                  />
                </SimpleGrid>
                <Textarea
                  label="About your business"
                  description="One or two sentences. The assistant uses this when customers ask who you are."
                  placeholder="e.g. A family dental clinic in Jawalakhel, open since 2012."
                  autosize
                  minRows={2}
                  maxRows={6}
                  disabled={!canWrite}
                  {...profileForm.getInputProps('description')}
                />
              </Section>

              <Section title="Contact details" description="Shared with customers when they ask how to reach you.">
                <SimpleGrid cols={{ base: 1, md: 2 }} spacing="lg">
                  <TextInput label="Phone number" placeholder="01-5550123" type="tel" disabled={!canWrite} {...profileForm.getInputProps('phone')} />
                  <TextInput label="Email address" placeholder="hello@yourbusiness.com" type="email" disabled={!canWrite} {...profileForm.getInputProps('email')} />
                  <TextInput label="Website" placeholder="https://yourbusiness.com" disabled={!canWrite} {...profileForm.getInputProps('website')} />
                  <TextInput label="Address" placeholder="Street, area, city" disabled={!canWrite} {...profileForm.getInputProps('address')} />
                </SimpleGrid>
              </Section>

              <Section title="Time and money" description="Used for appointment times, reminders and prices.">
                <SimpleGrid cols={{ base: 1, md: 2 }} spacing="lg">
                  <Select
                    label="Time zone"
                    withAsterisk
                    searchable
                    data={refData.timezones}
                    disabled={!canWrite}
                    // Select-all-on-focus so typing to search replaces the current value instead of appending to it.
                    onFocus={(e) => e.currentTarget.select()}
                    {...profileForm.getInputProps('timezone')}
                  />
                  <Select label="Currency" withAsterisk data={currencyOptions} disabled={!canWrite} {...profileForm.getInputProps('currency')} />
                </SimpleGrid>
              </Section>

              <SaveBar dirty={profileForm.isDirty()} saving={saving === 'profile'} canWrite={canWrite} onDiscard={() => profileForm.reset()} />
            </Stack>
          </form>
        </Tabs.Panel>

        <Tabs.Panel value="assistant">
          <form
            onSubmit={assistantForm.onSubmit((v) =>
              save(
                'assistant',
                { ...v, persona_name: blank(v.persona_name), sign_off: blank(v.sign_off) },
                'Assistant settings saved. They apply to new messages right away.',
              ),
            )}
          >
            <Stack gap="lg">
              <Section title="Personality" description="How your assistant introduces itself and sounds to customers.">
                <SimpleGrid cols={{ base: 1, md: 2 }} spacing="lg">
                  <TextInput
                    label="Assistant's name"
                    description="Leave empty and it introduces itself as your business's assistant."
                    placeholder="e.g. Priya"
                    disabled={!canWrite}
                    {...assistantForm.getInputProps('persona_name')}
                  />
                  <TextInput
                    label="Sign-off"
                    description="Optional closing line for longer messages."
                    placeholder="e.g. Team Lalitpur Smile"
                    disabled={!canWrite}
                    {...assistantForm.getInputProps('sign_off')}
                  />
                </SimpleGrid>
                <Stack gap={6}>
                  <Text fw={600} size="sm">
                    Tone of voice
                  </Text>
                  <SegmentedControl
                    maw={420}
                    disabled={!canWrite}
                    data={[
                      { value: 'casual', label: 'Friendly' },
                      { value: 'neutral', label: 'Balanced' },
                      { value: 'formal', label: 'Formal' },
                    ]}
                    {...assistantForm.getInputProps('formality')}
                  />
                </Stack>
                <Switch
                  label="Use an occasional emoji"
                  description="Only in warm moments, such as a greeting or a thank-you."
                  disabled={!canWrite}
                  checked={assistantForm.values.emoji_policy === 'default'}
                  onChange={(e) => assistantForm.setFieldValue('emoji_policy', e.currentTarget.checked ? 'default' : 'none')}
                />
              </Section>

              <Section title="Language" description="English, Nepali (Devanagari) and Romanized Nepali are supported.">
                <Radio.Group {...assistantForm.getInputProps('language_mode')}>
                  <Stack gap="md">
                    <Radio
                      value="automatic"
                      disabled={!canWrite}
                      label="Reply in the customer's language (recommended)"
                      description="Matches how the customer writes, and follows them if they switch."
                    />
                    <Radio
                      value="ask"
                      disabled={!canWrite}
                      label="Ask which language they prefer first"
                      description="The assistant asks at the start, then keeps to that language."
                    />
                  </Stack>
                </Radio.Group>
              </Section>

              <Section title="What your assistant talks about">
                <Radio.Group {...assistantForm.getInputProps('content_scope')}>
                  <Stack gap="md">
                    <Radio
                      value="single_business"
                      disabled={!canWrite}
                      label="Only my business (recommended)"
                      description="Questions about other companies are politely declined."
                    />
                    <Radio
                      value="aggregator"
                      disabled={!canWrite}
                      label="My business and the organisations I cover"
                      description="For information hubs, such as a consultancy that answers questions about specific colleges."
                    />
                  </Stack>
                </Radio.Group>
              </Section>

              <SaveBar dirty={assistantForm.isDirty()} saving={saving === 'assistant'} canWrite={canWrite} onDiscard={() => assistantForm.reset()} />
            </Stack>
          </form>
        </Tabs.Panel>

        <Tabs.Panel value="bookings">
          <form onSubmit={bookingForm.onSubmit((v) => save('bookings', v, 'Booking settings saved.'))}>
            <Stack gap="lg">
              <Section title="Bookings in chat">
                <Switch
                  size="lg"
                  label="Customers can book appointments through chat"
                  description="Turn this off if you only answer questions. The assistant will then offer to connect customers with your team instead."
                  disabled={!canWrite}
                  {...bookingForm.getInputProps('booking_enabled', { type: 'checkbox' })}
                />
              </Section>

              <Section
                title="Appointment reminders"
                description="Customers get a reminder by email (and by text, if SMS is on) before a confirmed appointment. Bookings made after the reminder time has already passed don't get one."
              >
                <Switch
                  size="lg"
                  label="Send reminders automatically"
                  disabled={!canWrite}
                  {...bookingForm.getInputProps('reminder_enabled', { type: 'checkbox' })}
                />
                {bookingForm.values.reminder_enabled && (
                  <Group align="flex-end" gap="md" wrap="wrap">
                    <Select
                      label="When to remind"
                      w={220}
                      data={REMINDER_PRESETS}
                      value={reminderPreset}
                      disabled={!canWrite}
                      allowDeselect={false}
                      onChange={(v) => {
                        if (v && v !== 'custom') bookingForm.setFieldValue('reminder_minutes_before', Number(v))
                        else if (v === 'custom') bookingForm.setFieldValue('reminder_minutes_before', 30)
                      }}
                    />
                    {reminderPreset === 'custom' && (
                      <NumberInput
                        label="Minutes before"
                        w={180}
                        min={5}
                        max={1440}
                        disabled={!canWrite}
                        {...bookingForm.getInputProps('reminder_minutes_before')}
                      />
                    )}
                  </Group>
                )}
              </Section>

              <Section
                title="Alerts for you"
                description="Sent to the email of every owner and admin login."
              >
                <Switch
                  size="lg"
                  label="Email me when a customer needs a person or books in chat"
                  description="So you can reply quickly without keeping the dashboard open."
                  disabled={!canWrite}
                  {...bookingForm.getInputProps('owner_alerts_enabled', { type: 'checkbox' })}
                />
              </Section>

              <SaveBar dirty={bookingForm.isDirty()} saving={saving === 'bookings'} canWrite={canWrite} onDiscard={() => bookingForm.reset()} />
            </Stack>
          </form>
        </Tabs.Panel>

        <Tabs.Panel value="account">
          <AccountTab />
        </Tabs.Panel>

        <Tabs.Panel value="plan">
          <Section title="Your plan">
            {plan ? (
              <Stack gap="md">
                <Group gap="sm">
                  <Badge size="lg" color={plan.plan === 'premium' ? 'grape' : 'gray'} variant={plan.plan === 'premium' ? 'filled' : 'light'}>
                    {plan.plan === 'premium' ? 'Premium' : 'Free'}
                  </Badge>
                  <Text c="dimmed" size="sm">
                    {plan.plan === 'premium' ? 'Every feature is included.' : 'The essentials for answering and booking customers.'}
                  </Text>
                </Group>
                {plan.features.length > 0 && (
                  <div>
                    <Text fw={600} size="sm" mb={6}>
                      Included in your plan
                    </Text>
                    <List size="sm" spacing={4}>
                      {plan.features.map((f) => (
                        <List.Item key={f}>{f}</List.Item>
                      ))}
                    </List>
                  </div>
                )}
                {plan.plan !== 'premium' && (
                  <Paper p="lg" radius="lg" className="ng-upgrade">
                    <Stack gap="sm">
                      <Text fw={700} size="lg">
                        Premium adds
                      </Text>
                      <List size="sm" spacing={4}>
                        <List.Item>Online deposits through eSewa and Khalti</List.Item>
                        <List.Item>Google Calendar sync</List.Item>
                        <List.Item>SMS confirmations and reminders</List.Item>
                        <List.Item>Yearly reports with year-over-year comparison</List.Item>
                      </List>
                      {business.upgrade_requested_at ? (
                        <Text size="sm" fw={600}>
                          You asked to upgrade on {new Date(business.upgrade_requested_at).toLocaleDateString(undefined, { day: 'numeric', month: 'long' })}.
                          Our team will contact you at {business.email || 'your login email'} to set it up.
                        </Text>
                      ) : (
                        <Text size="sm" c="dimmed">
                          Ask for Premium and our team will contact you to set up payment.
                        </Text>
                      )}
                      {canWrite && (
                        <Button
                          style={{ alignSelf: 'flex-start' }}
                          loading={requesting}
                          variant={business.upgrade_requested_at ? 'default' : 'filled'}
                          onClick={requestUpgrade}
                        >
                          {business.upgrade_requested_at ? 'Send the request again' : 'Request Premium'}
                        </Button>
                      )}
                    </Stack>
                  </Paper>
                )}
              </Stack>
            ) : (
              <Skeleton height={80} />
            )}
          </Section>
        </Tabs.Panel>
      </Tabs>
    </Stack>
  )
}
