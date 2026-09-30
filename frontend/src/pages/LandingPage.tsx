import { Link } from 'react-router-dom'
import { Box, Button, Group, Stack, Text, Title } from '@mantine/core'
import { IconBrandWhatsapp, IconCalendarEvent, IconMoonStars, IconSparkles } from '@tabler/icons-react'

const HIGHLIGHTS = [
  { icon: IconBrandWhatsapp, label: 'Replies on WhatsApp, Instagram & web', tint: 'linear-gradient(135deg,#6EE7B7,#059669)' },
  { icon: IconCalendarEvent, label: 'Books appointments for you', tint: 'linear-gradient(135deg,#F472B6,#DB2777)' },
  { icon: IconSparkles, label: 'Learns from your own answers', tint: 'linear-gradient(135deg,#C084FC,#7C3AED)' },
]

export default function LandingPage() {
  return (
    <Box className="ng-auth-stage">
      <span className="ng-orb ng-orb-a" aria-hidden />
      <span className="ng-orb ng-orb-b" aria-hidden />
      <span className="ng-orb ng-orb-c" aria-hidden />

      <Box className="ng-auth-card ng-page" maw={560}>
        <Stack align="center" gap="lg" ta="center">
          <span className="ng-tile ng-logo" style={{ width: 64, height: 64, borderRadius: 20 }}>
            <IconMoonStars size={34} stroke={1.8} />
          </span>
          <Stack gap={8} align="center">
            <Title order={1} style={{ letterSpacing: '-0.03em' }}>
              Night Guard <span className="ng-gradient-text">AI</span>
            </Title>
            <Text size="lg" c="dimmed" maw={420}>
              Your AI receptionist. It answers customers day and night, so you never miss a booking.
            </Text>
          </Stack>

          <Stack gap={10} w="100%" maw={380}>
            {HIGHLIGHTS.map(({ icon: Icon, label, tint }) => (
              <Group key={label} gap="sm" wrap="nowrap" className="ng-chip">
                <span className="ng-tile" style={{ width: 32, height: 32, background: tint }}>
                  <Icon size={18} stroke={2} />
                </span>
                <Text fw={600} size="sm" ta="left">
                  {label}
                </Text>
              </Group>
            ))}
          </Stack>

          <Group gap="sm" justify="center" w="100%" mt={4}>
            <Button component={Link} to="/login" size="lg" radius="xl" px={36}>
              Log in
            </Button>
            <Button component={Link} to="/register" size="lg" radius="xl" variant="default" px={28}>
              Create an account
            </Button>
          </Group>
        </Stack>
      </Box>
    </Box>
  )
}
