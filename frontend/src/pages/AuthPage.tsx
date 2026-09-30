import { useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { Alert, Box, Button, PasswordInput, SegmentedControl, Stack, Text, TextInput, Title } from '@mantine/core'
import { IconMoonStars } from '@tabler/icons-react'
import { useForm } from '@mantine/form'
import { useAuth } from '../auth/AuthContext'
import { ApiError } from '../api/client'

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
              {mode === 'login' ? 'Welcome back' : 'Create your account'}
            </Title>
            <Text c="dimmed" size="md">
              {mode === 'login' ? 'Log in to your Night Guard AI dashboard.' : 'Set up your business in under a minute.'}
            </Text>
          </Stack>
          <SegmentedControl
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
          />

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

          {mode === 'login' ? (
            <form onSubmit={loginForm.onSubmit(handleLogin)}>
              <Stack gap="md">
                <TextInput label="Email" type="email" placeholder="you@business.com" autoComplete="email" required {...loginForm.getInputProps('email')} />
                <PasswordInput label="Password" autoComplete="current-password" required {...loginForm.getInputProps('password')} />
                <Button type="submit" loading={submitting} fullWidth mt="xs" size="lg" radius="xl">
                  Log in
                </Button>
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
