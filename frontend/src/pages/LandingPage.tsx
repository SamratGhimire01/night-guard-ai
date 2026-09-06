import { Link } from 'react-router-dom'
import { Box, Button, Stack, Text, Title } from '@mantine/core'

export default function LandingPage() {
  return (
    <Box
      style={{
        minHeight: '100vh',
        background: '#000',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
      }}
    >
      <Stack align="center" gap="xl">
        <Stack align="center" gap={4}>
          <Title order={1} c="white" fw={800} style={{ letterSpacing: '-0.02em' }}>
            Night Guard AI
          </Title>
          <Text c="dimmed" size="sm">
            Business dashboard
          </Text>
        </Stack>
        <Button component={Link} to="/login" size="lg" radius="md" color="grape">
          Login / Register
        </Button>
      </Stack>
    </Box>
  )
}
