import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Button, Group, Paper, Progress, Stack, Text, Title, UnstyledButton } from '@mantine/core'
import { IconArrowRight, IconCircleCheckFilled, IconCircleDashed } from '@tabler/icons-react'
import { apiFetch } from '../api/client'

interface SetupStep {
  key: string
  title: string
  description: string
  done: boolean
  link: string
}

interface SetupStatus {
  steps: SetupStep[]
  completed: number
  total: number
}

const HIDE_KEY = 'ngai_setup_hidden'

/** "Get set up" on the Overview: the few things a new business must do before the assistant can really help. Each
 * step ticks itself off from real data; the card goes away once everything is done (or the owner hides it). */
export default function SetupChecklist() {
  const [status, setStatus] = useState<SetupStatus | null>(null)
  const [hidden, setHidden] = useState(() => {
    try {
      return sessionStorage.getItem(HIDE_KEY) === '1'
    } catch {
      return false
    }
  })

  useEffect(() => {
    apiFetch<SetupStatus>('/business/setup-status').then(setStatus).catch(() => setStatus(null))
  }, [])

  if (!status || hidden || status.completed === status.total) return null
  const next = status.steps.find((s) => !s.done)

  return (
    <Paper p={{ base: 'md', sm: 'xl' }} className="ng-setup">
      <Stack gap="lg">
        <Group justify="space-between" align="flex-start" wrap="wrap" gap="sm">
          <div>
            <Title order={3}>Get set up</Title>
            <Text size="sm" c="dimmed" mt={4}>
              {status.completed === 0
                ? 'A few steps and your assistant is ready for customers.'
                : `${status.completed} of ${status.total} done. Keep going.`}
            </Text>
          </div>
          <Button
            variant="subtle"
            color="gray"
            size="sm"
            onClick={() => {
              setHidden(true)
              try {
                sessionStorage.setItem(HIDE_KEY, '1')
              } catch {
                /* storage blocked: hidden until reload */
              }
            }}
          >
            Hide for now
          </Button>
        </Group>
        <Progress value={(status.completed / status.total) * 100} size="lg" radius="xl" aria-label="Setup progress" />
        <Stack gap={6}>
          {status.steps.map((step) => (
            <UnstyledButton
              key={step.key}
              component={Link}
              to={step.link}
              className="ng-setup-step"
              data-done={step.done || undefined}
              data-next={step === next || undefined}
            >
              {step.done ? (
                <IconCircleCheckFilled size={26} className="ng-setup-icon-done" />
              ) : (
                <IconCircleDashed size={26} className="ng-setup-icon" />
              )}
              <div style={{ flex: 1, minWidth: 0 }}>
                <Text fw={700} td={step.done ? 'line-through' : undefined} c={step.done ? 'dimmed' : undefined}>
                  {step.title}
                </Text>
                {!step.done && (
                  <Text size="sm" c="dimmed">
                    {step.description}
                  </Text>
                )}
              </div>
              {!step.done && <IconArrowRight size={20} className="ng-setup-arrow" />}
            </UnstyledButton>
          ))}
        </Stack>
      </Stack>
    </Paper>
  )
}
