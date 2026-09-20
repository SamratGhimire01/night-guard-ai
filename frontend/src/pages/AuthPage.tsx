import { useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { Alert, Box, Button, Paper, PasswordInput, SegmentedControl, Stack, TextInput, Title } from '@mantine/core'
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
    <Box style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'var(--mantine-color-body)' }}>
      <Paper withBorder shadow="sm" radius="md" p="xl" w={380}>
        <Stack gap="md">
          <Title order={3} ta="center">
            Night Guard AI
          </Title>
          <SegmentedControl
            fullWidth
            value={mode}
            onChange={(value) => {
              setMode(value as 'login' | 'register')
              setError(null)
              clearSessionMessage()
            }}
            data={[
              { label: 'Login', value: 'login' },
              { label: 'Register', value: 'register' },
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
              <Stack gap="sm">
                <TextInput label="Email" type="email" required {...loginForm.getInputProps('email')} />
                <PasswordInput label="Password" required {...loginForm.getInputProps('password')} />
                <Button type="submit" loading={submitting} fullWidth mt="xs">
                  Log in
                </Button>
              </Stack>
            </form>
          ) : (
            <form onSubmit={registerForm.onSubmit(handleRegister)}>
              <Stack gap="sm">
                <TextInput label="Business name" required {...registerForm.getInputProps('business_name')} />
                <TextInput label="Timezone" required {...registerForm.getInputProps('timezone')} />
                <TextInput label="Email" type="email" required {...registerForm.getInputProps('email')} />
                <PasswordInput
                  label="Password"
                  required
                  description="At least 8 characters, with a letter and a digit."
                  {...registerForm.getInputProps('password')}
                />
                <Button type="submit" loading={submitting} fullWidth mt="xs">
                  Create business account
                </Button>
              </Stack>
            </form>
          )}
        </Stack>
      </Paper>
    </Box>
  )
}
