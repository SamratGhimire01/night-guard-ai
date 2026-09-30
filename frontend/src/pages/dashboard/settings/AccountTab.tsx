import { useEffect, useState } from 'react'
import {
  Alert,
  Badge,
  Button,
  Code,
  CopyButton,
  Group,
  Modal,
  Paper,
  PasswordInput,
  Select,
  SimpleGrid,
  Skeleton,
  Stack,
  Table,
  Text,
  TextInput,
  Title,
} from '@mantine/core'
import { useForm } from '@mantine/form'
import { notifications } from '@mantine/notifications'
import { IconCheck, IconCopy, IconTrash, IconUserPlus } from '@tabler/icons-react'
import { apiFetch, ApiError } from '../../../api/client'
import type { CurrentUser, TeamInviteResult, TeamMember, TokenResponse } from '../../../api/types'
import { useAuth } from '../../../auth/AuthContext'
import { friendlyDateTime } from '../../../lib/dates'

const ROLE_LABEL: Record<string, string> = { owner: 'Owner', admin: 'Admin', staff: 'Staff' }
const ROLE_HELP: Record<string, string> = {
  admin: 'Can change settings, services and the team (except owners).',
  staff: 'Can use the Inbox, appointments and check-in. Cannot change settings.',
}

function errorText(err: unknown, fallback: string) {
  return err instanceof ApiError ? err.message : fallback
}

function ChangePassword() {
  const { startSession } = useAuth()
  const [saving, setSaving] = useState(false)
  const form = useForm({
    initialValues: { current: '', next: '', confirm: '' },
    validate: {
      current: (v) => (v ? null : 'Enter your current password.'),
      next: (v) =>
        v.length < 8 ? 'Use at least 8 characters.' : !/[A-Za-z]/.test(v) || !/[0-9]/.test(v) ? 'Use at least one letter and one number.' : null,
      confirm: (v, values) => (v === values.next ? null : "The two passwords don't match."),
    },
  })

  async function submit(values: typeof form.values) {
    setSaving(true)
    try {
      const res = await apiFetch<TokenResponse>('/auth/change-password', {
        method: 'POST',
        body: JSON.stringify({ current_password: values.current, new_password: values.next }),
      })
      startSession(res.access_token)
      form.reset()
      notifications.show({ color: 'green', message: 'Password changed. Any other devices have been logged out.' })
    } catch (err) {
      notifications.show({ color: 'red', message: errorText(err, 'Could not change the password.') })
    } finally {
      setSaving(false)
    }
  }

  return (
    <Paper p={{ base: 'md', sm: 'xl' }}>
      <form onSubmit={form.onSubmit(submit)}>
        <Stack gap="lg">
          <div>
            <Title order={3}>Change password</Title>
            <Text c="dimmed" size="sm" mt={4}>
              Other devices logged in to your account will be logged out.
            </Text>
          </div>
          <SimpleGrid cols={{ base: 1, md: 3 }} spacing="lg">
            <PasswordInput label="Current password" autoComplete="current-password" {...form.getInputProps('current')} />
            <PasswordInput
              label="New password"
              description="8+ characters, a letter and a number"
              autoComplete="new-password"
              {...form.getInputProps('next')}
            />
            <PasswordInput label="Type it again" autoComplete="new-password" {...form.getInputProps('confirm')} />
          </SimpleGrid>
          <Button type="submit" loading={saving} style={{ alignSelf: 'flex-start' }}>
            Change password
          </Button>
        </Stack>
      </form>
    </Paper>
  )
}

function Team({ me }: { me: CurrentUser }) {
  const [members, setMembers] = useState<TeamMember[] | null>(null)
  const [adding, setAdding] = useState(false)
  const [invited, setInvited] = useState<TeamInviteResult | null>(null)
  const [removing, setRemoving] = useState<TeamMember | null>(null)
  const [busy, setBusy] = useState(false)
  const roleChoices = me.role === 'owner' ? ['admin', 'staff'] : ['staff']
  const form = useForm({
    initialValues: { email: '', role: 'staff' },
    validate: { email: (v) => (/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(v.trim()) ? null : 'Enter a full email address.') },
  })

  const load = () => apiFetch<TeamMember[]>('/team').then(setMembers)
  useEffect(() => {
    load()
  }, [])

  const canManage = (m: TeamMember) => m.id !== me.user_id && m.role !== 'owner' && (me.role === 'owner' || m.role === 'staff')

  async function invite(values: typeof form.values) {
    setBusy(true)
    try {
      const res = await apiFetch<TeamInviteResult>('/team', {
        method: 'POST',
        body: JSON.stringify({ email: values.email.trim(), role: values.role }),
      })
      setAdding(false)
      setInvited(res)
      form.reset()
      load()
    } catch (err) {
      notifications.show({ color: 'red', message: errorText(err, 'Could not add this person.') })
    } finally {
      setBusy(false)
    }
  }

  async function changeRole(member: TeamMember, role: string) {
    try {
      await apiFetch(`/team/${member.id}`, { method: 'PATCH', body: JSON.stringify({ role }) })
      notifications.show({ color: 'green', message: `${member.email} is now ${ROLE_LABEL[role].toLowerCase()}.` })
      load()
    } catch (err) {
      notifications.show({ color: 'red', message: errorText(err, 'Could not change the role.') })
    }
  }

  async function remove() {
    if (!removing) return
    setBusy(true)
    try {
      await apiFetch(`/team/${removing.id}`, { method: 'DELETE' })
      notifications.show({ message: `${removing.email} can no longer log in.` })
      setRemoving(null)
      load()
    } catch (err) {
      notifications.show({ color: 'red', message: errorText(err, 'Could not remove this person.') })
    } finally {
      setBusy(false)
    }
  }

  return (
    <Paper p={{ base: 'md', sm: 'xl' }}>
      <Stack gap="lg">
        <Group justify="space-between" align="flex-end" wrap="wrap">
          <div>
            <Title order={3}>Team</Title>
            <Text c="dimmed" size="sm" mt={4}>
              Give each person their own login instead of sharing yours.
            </Text>
          </div>
          <Button leftSection={<IconUserPlus size={18} />} onClick={() => setAdding(true)}>
            Add a person
          </Button>
        </Group>

        <Table.ScrollContainer minWidth={560}>
          <Table>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Email</Table.Th>
                <Table.Th>Access</Table.Th>
                <Table.Th>Added</Table.Th>
                <Table.Th />
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {members === null
                ? [0, 1].map((i) => (
                    <Table.Tr key={i}>
                      <Table.Td colSpan={4}>
                        <Skeleton height={16} />
                      </Table.Td>
                    </Table.Tr>
                  ))
                : members.map((m) => (
                    <Table.Tr key={m.id}>
                      <Table.Td>
                        <Group gap={8} wrap="nowrap">
                          <Text size="sm" fw={600}>
                            {m.email}
                          </Text>
                          {m.id === me.user_id && (
                            <Badge size="sm" color="gray">
                              You
                            </Badge>
                          )}
                        </Group>
                      </Table.Td>
                      <Table.Td>
                        {canManage(m) ? (
                          <Select
                            size="sm"
                            w={130}
                            aria-label={`Access for ${m.email}`}
                            data={roleChoices.map((r) => ({ value: r, label: ROLE_LABEL[r] }))}
                            value={m.role}
                            allowDeselect={false}
                            onChange={(v) => v && v !== m.role && changeRole(m, v)}
                          />
                        ) : (
                          <Badge color={m.role === 'owner' ? 'grape' : 'gray'}>{ROLE_LABEL[m.role] ?? m.role}</Badge>
                        )}
                      </Table.Td>
                      <Table.Td>
                        <Text size="sm" c="dimmed">
                          {friendlyDateTime(m.created_at)}
                        </Text>
                      </Table.Td>
                      <Table.Td ta="right">
                        {canManage(m) && (
                          <Button variant="subtle" color="red" size="sm" leftSection={<IconTrash size={16} />} onClick={() => setRemoving(m)}>
                            Remove
                          </Button>
                        )}
                      </Table.Td>
                    </Table.Tr>
                  ))}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      </Stack>

      <Modal opened={adding} onClose={() => setAdding(false)} title="Add a person">
        <form onSubmit={form.onSubmit(invite)}>
          <Stack gap="md">
            <TextInput label="Their email" type="email" placeholder="name@example.com" {...form.getInputProps('email')} data-autofocus />
            <Select
              label="Access"
              data={roleChoices.map((r) => ({ value: r, label: ROLE_LABEL[r] }))}
              allowDeselect={false}
              description={ROLE_HELP[form.values.role]}
              {...form.getInputProps('role')}
            />
            <Text size="sm" c="dimmed">
              We'll email them a link to choose their password.
            </Text>
            <Button type="submit" loading={busy}>
              Add and send invite
            </Button>
          </Stack>
        </form>
      </Modal>

      <Modal opened={!!invited} onClose={() => setInvited(null)} title="Invite sent">
        {invited && (
          <Stack gap="md">
            <Text size="sm">
              We emailed <b>{invited.member.email}</b> a link to choose their password. If it doesn't arrive, send them this
              link yourself. It works for 7 days.
            </Text>
            <Code block style={{ wordBreak: 'break-all', whiteSpace: 'pre-wrap' }}>
              {invited.invite_link}
            </Code>
            <CopyButton value={invited.invite_link}>
              {({ copied, copy }) => (
                <Button color={copied ? 'teal' : undefined} leftSection={copied ? <IconCheck size={16} /> : <IconCopy size={16} />} onClick={copy}>
                  {copied ? 'Copied' : 'Copy link'}
                </Button>
              )}
            </CopyButton>
          </Stack>
        )}
      </Modal>

      <Modal opened={!!removing} onClose={() => setRemoving(null)} title="Remove this person?">
        <Stack gap="md">
          <Text size="sm">
            <b>{removing?.email}</b> will be logged out and won't be able to log in again. You can add them back later.
          </Text>
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setRemoving(null)}>
              Keep
            </Button>
            <Button color="red" loading={busy} onClick={remove}>
              Remove
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Paper>
  )
}

export default function AccountTab() {
  const [me, setMe] = useState<CurrentUser | null>(null)
  useEffect(() => {
    apiFetch<CurrentUser>('/auth/me').then(setMe)
  }, [])
  if (!me) return <Skeleton height={240} radius="lg" />
  return (
    <Stack gap="lg">
      <Paper p={{ base: 'md', sm: 'xl' }}>
        <Group justify="space-between" wrap="wrap">
          <div>
            <Text size="sm" c="dimmed">
              Logged in as
            </Text>
            <Text fw={700}>{me.email}</Text>
          </div>
          <Badge size="lg" color={me.role === 'owner' ? 'grape' : 'gray'}>
            {ROLE_LABEL[me.role] ?? me.role}
          </Badge>
        </Group>
      </Paper>
      <ChangePassword />
      {me.role === 'owner' || me.role === 'admin' ? (
        <Team me={me} />
      ) : (
        <Alert color="gray">Ask an owner or admin if someone on your team needs a login.</Alert>
      )}
    </Stack>
  )
}
