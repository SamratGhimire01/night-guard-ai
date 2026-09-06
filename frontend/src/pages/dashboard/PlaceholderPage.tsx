import { Stack, Text, Title } from '@mantine/core'

export default function PlaceholderPage({ title }: { title: string }) {
  return (
    <Stack gap={4}>
      <Title order={2}>{title}</Title>
      <Text c="dimmed">This section is coming in a later phase.</Text>
    </Stack>
  )
}
