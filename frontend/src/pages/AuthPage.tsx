import { useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { Alert, Anchor, Box, Button, PasswordInput, SegmentedControl, Stack, Text, TextInput, Title } from '@mantine/core'
import { IconMoonStars } from '@tabler/icons-react'
import { useForm } from '@mantine/form'
import { useAuth } from '../auth/AuthContext'
import { apiFetch, ApiError } from '../api/client'

const detectedTimezone = Intl.DateTimeFormat().resolvedOptions().timeZone

export default function AuthPage() {
  const location = useLocation()
  const navigate = useNavigate()
  const { login, register, sessionMessage, clearSessionMessage } = useAuth()
  const [mode, setMode] = useState<'login' | 'register'>(
    location.pathname === '/register' ? 'register' : 'login',
  )
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [forgot, setForgot] = useState(false)
  const [resetSentTo, setResetSentTo] = useState<string | null>(null)
  const forgotForm = useForm({ initialValues: { email: '' } })

  async function handleForgot(values: { email: string }) {
    setError(null)
    setSubmitting(true)
    try {
      await apiFetch('/auth/forgot-password', { method: 'POST', body: JSON.stringify({ email: values.email.trim() }) })
      setResetSentTo(values.email.trim())
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Something went wrong. Please try again.')
    } finally {
      setSubmitting(false)
    }
  }

  const loginForm = useForm({
    initialValues: { email: '', password: '' },
  })

  const registerForm = useForm({
    initialValues: { business_name: '', timezone: detectedTimezone, email: '', password: '' },
  })

  async function handleLogin(values: typeof loginForm.values) {
    setError(null)
    setSubmitting(true)
    try {
      await login(values)
      navigate('/dashboard')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Login failed.')
    } finally {
      setSubmitting(false)
    }
  }

  async function handleRegister(values: typeof registerForm.values) {
    setError(null)
    setSubmitting(true)
    try {
      await register(values)
      // Register doesn't return a token (Phase 3 contract) — log in right
      // after with the same credentials so registering lands you in the
      // dashboard, not back at a login form you have to fill out again.
      await login({ email: values.email, password: values.password })
      navigate('/dashboard')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Registration failed.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Box className="ng-auth-stage">
      <span className="ng-orb ng-orb-a" aria-hidden />
      <span className="ng-orb ng-orb-b" aria-hidden />
      <span className="ng-orb ng-orb-c" aria-hidden />
      <Box className="ng-auth-card ng-page" w="100%" maw={440}>
        <Stack gap="lg">
          <Stack gap={10} align="center" ta="center">
            <span className="ng-tile ng-logo" style={{ width: 56, height: 56, borderRadius: 18 }}>
              <IconMoonStars size={30} stroke={1.8} />
            </span>
            <Title order={2} style={{ letterSpacing: '-0.02em' }}>
              {forgot ? 'Reset your password' : mode === 'login' ? 'Welcome back' : 'Create your account'}
            </Title>
            <Text c="dimmed" size="md">
              {forgot ? 'It only takes a minute.' : mode === 'login' ? 'Log in to your Night Guard AI dashboard.' : 'Set up your business in under a minute.'}
            </Text>
          </Stack>
          {!forgot && <SegmentedControl
            fullWidth
            value={mode}
            onChange={(value) => {
              setMode(value as 'login' | 'register')
              setError(null)
              clearSessionMessage()
            }}
            data={[
              { label: 'Log in', value: 'login' },
              { label: 'New account', value: 'register' },
            ]}
          />}

          {sessionMessage && (
            <Alert color="yellow" variant="light">
              {sessionMessage}
            </Alert>
          )}
          {error && (
            <Alert color="red" variant="light">
              {error}
            </Alert>
          )}

          {forgot ? (
            resetSentTo ? (
              <Stack gap="md">
                <Alert color="green" title="Check your email">
                  If {resetSentTo} has an account, we've sent a link to choose a new password. It works for one hour.
                </Alert>
                <Button variant="default" fullWidth size="lg" radius="xl" onClick={() => { setForgot(false); setResetSentTo(null) }}>
                  Back to log in
                </Button>
              </Stack>
            ) : (
              <form onSubmit={forgotForm.onSubmit(handleForgot)}>
                <Stack gap="md">
                  <Text size="sm" c="dimmed">
                    Enter the email you log in with and we'll send you a link to choose a new password.
                  </Text>
                  <TextInput label="Email" type="email" placeholder="you@business.com" autoComplete="email" required {...forgotForm.getInputProps('email')} />
                  <Button type="submit" loading={submitting} fullWidth size="lg" radius="xl">
                    Send reset link
                  </Button>
                  <Anchor component="button" type="button" size="sm" onClick={() => setForgot(false)}>
                    Back to log in
                  </Anchor>
                </Stack>
              </form>
            )
          ) : mode === 'login' ? (
            <form onSubmit={loginForm.onSubmit(handleLogin)}>
              <Stack gap="md">
                <TextInput label="Email" type="email" placeholder="you@business.com" autoComplete="email" required {...loginForm.getInputProps('email')} />
                <PasswordInput label="Password" autoComplete="current-password" required {...loginForm.getInputProps('password')} />
                <Button type="submit" loading={submitting} fullWidth mt="xs" size="lg" radius="xl">
                  Log in
                </Button>
                <Anchor component="button" type="button" size="sm" ta="center" onClick={() => { setForgot(true); setError(null) }}>
                  Forgot your password?
                </Anchor>
              </Stack>
            </form>
          ) : (
            <form onSubmit={registerForm.onSubmit(handleRegister)}>
              <Stack gap="md">
                <TextInput label="Business name" required {...registerForm.getInputProps('business_name')} />
                <TextInput label="Timezone" required {...registerForm.getInputProps('timezone')} />
                <TextInput label="Email" type="email" required {...registerForm.getInputProps('email')} />
                <PasswordInput
                  label="Password"
                  required
                  description="At least 8 characters, with a letter and a digit."
                  {...registerForm.getInputProps('password')}
                />
                <Button type="submit" loading={submitting} fullWidth mt="xs" size="lg" radius="xl">
                  Create business account
                </Button>
              </Stack>
            </form>
          )}
        </Stack>
      </Box>
    </Box>
  )
}
