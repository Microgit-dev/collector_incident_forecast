import { Card, Stack, Text, Title } from '@mantine/core'

/** Экран-заглушка для разделов, которые подключаются следующими эпиками дорожной карты. */
export function PlannedPage({ title, epic, description }: { title: string; epic: string; description: string }) {
  return (
    <Stack>
      <Title order={3}>{title}</Title>
      <Card withBorder radius="md">
        <Text>{description}</Text>
        <Text size="sm" c="dimmed" mt="xs">
          Раздел в работе — {epic} (см. ROADMAP.md)
        </Text>
      </Card>
    </Stack>
  )
}
