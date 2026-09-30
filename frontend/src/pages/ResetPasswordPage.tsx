import { useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { Alert, Anchor, Box, Button, PasswordInput, Stack, Text, Title } from '@mantine/core'
import { useForm } from '@mantine/form'
import { IconMoonStars } from '@tabler/icons-react'
import { apiFetch, ApiError } from '../api/client'
import type { TokenResponse } from '../api/types'
import { useAuth } from '../auth/AuthContext'

// Only to choose the wording (reset vs. invite). The server checks the token itself.
function linkPurpose(token: string): string | null {
  try {
    const payload = JSON.parse(atob(token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/')))
    return typeof payload.purpose === 'string' ? payload.purpose : null
  } catch {
    return null
  }
}

/** Where emailed "reset your password" and "you've been added to the team" links land. */
export default function ResetPasswordPage() {
  const [params] = useSearchParams()
  const token = params.get('token') ?? ''
  const invite = linkPurpose(token) === 'invite'
  const navigate = useNavigate()
  const { startSession } = useAuth()
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  const form = useForm({
    initialValues: { password: '', confirm: '' },
    validate: {
      password: (v) =>
        v.length < 8 ? 'Use at least 8 characters.' : !/[A-Za-z]/.test(v) || !/[0-9]/.test(v) ? 'Use at least one letter and one number.' : null,
      confirm: (v, values) => (v === values.password ? null : "The two passwords don't match."),
    },
  })

  async function submit(values: { password: string }) {
    setError(null)
    setSubmitting(true)
    try {
      const res = await apiFetch<TokenResponse>('/auth/reset-password', {
        method: 'POST',
        body: JSON.stringify({ token, new_password: values.password }),
      })
      startSession(res.access_token)
      navigate('/dashboard')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Something went wrong. Please try again.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Box className="ng-auth-stage">
      <span className="ng-orb ng-orb-a" aria-hidden />
      <span className="ng-orb ng-orb-b" aria-hidden />
      <Box className="ng-auth-card ng-page" w="100%" maw={440}>
        <Stack gap="lg">
          <Stack gap={10} align="center" ta="center">
            <span className="ng-tile ng-logo" style={{ width: 56, height: 56, borderRadius: 18 }}>
              <IconMoonStars size={30} stroke={1.8} />
            </span>
            <Title order={2}>{invite ? 'Welcome to the team' : 'Choose a new password'}</Title>
            <Text c="dimmed">
              {invite ? 'Choose a password for your Night Guard AI login.' : "You'll be logged in straight after."}
            </Text>
          </Stack>

          {!token ? (
            <Alert color="red">This link is incomplete. Open it again from your email, or ask for a new one.</Alert>
          ) : (
            <form onSubmit={form.onSubmit(submit)}>
              <Stack gap="md">
                {error && <Alert color="red">{error}</Alert>}
                <PasswordInput
                  label="New password"
                  description="At least 8 characters, with a letter and a number."
                  autoComplete="new-password"
                  required
                  {...form.getInputProps('password')}
                />
                <PasswordInput label="Type it again" autoComplete="new-password" required {...form.getInputProps('confirm')} />
                <Button type="submit" loading={submitting} fullWidth size="lg" radius="xl">
                  {invite ? 'Save and open my dashboard' : 'Save new password'}
                </Button>
              </Stack>
            </form>
          )}
          <Anchor component={Link} to="/login" size="sm" ta="center">
            Back to log in
          </Anchor>
        </Stack>
      </Box>
    </Box>
  )
}
