import { Alert, Avatar, Badge, Box, Breadcrumbs, Card, Group, Loader, Stack, Text, Title, Tooltip } from '@mantine/core'
import { IconArrowUp, IconCrown, IconInfoCircle } from '@tabler/icons-react'
import { useQuery } from '@tanstack/react-query'

import { api } from '../api/client'
import type { Team, TeamKind } from '../api/types'
import { useAuth } from '../auth/AuthContext'

const KIND_COLOR: Record<TeamKind, string> = {
  management: 'violet',
  ods: 'blue',
  unit: 'cyan',
  brigade: 'orange',
  analytics: 'teal',
  support: 'gray',
}

function initials(last: string, first: string, username: string) {
  return (last[0] ?? '') + (first[0] ?? '') || username.slice(0, 2).toUpperCase()
}

function TeamCard({ team, byParent, mine }: { team: Team; byParent: Map<number | null, Team[]>; mine?: number }) {
  const children = byParent.get(team.id) ?? []
  return (
    <Stack gap="xs">
      <Card
        withBorder
        radius="md"
        padding="sm"
        style={team.id === mine ? { borderColor: 'var(--mantine-color-blue-5)' } : undefined}
      >
        <Group justify="space-between" wrap="wrap" gap="xs">
          <Group gap="xs">
            <Text fw={600}>{team.name}</Text>
            <Badge variant="light" color={KIND_COLOR[team.kind]}>
              {team.kind_display}
            </Badge>
            {team.id === mine && <Badge variant="filled">Ваша команда</Badge>}
          </Group>
          <Text size="sm" c="dimmed">
            Зона: {team.scope_node_name ?? 'не назначена'}
          </Text>
        </Group>
        <Group gap="md" mt="xs" wrap="wrap">
          {team.members.length === 0 && (
            <Text size="sm" c="dimmed">
              Нет участников
            </Text>
          )}
          {team.members.map((m) => (
            <Group key={m.id} gap={6} wrap="nowrap">
              <Avatar size="sm" radius="xl" color={KIND_COLOR[team.kind]}>
                {initials(m.last_name, m.first_name, m.username)}
              </Avatar>
              <div>
                <Group gap={4} wrap="nowrap">
                  <Text size="sm">{[m.last_name, m.first_name].filter(Boolean).join(' ') || m.username}</Text>
                  {team.lead === m.id && (
                    <Tooltip label="Руководитель команды">
                      <IconCrown size={14} color="var(--mantine-color-yellow-6)" />
                    </Tooltip>
                  )}
                </Group>
                <Text size="xs" c="dimmed">
                  {m.position || m.roles.map((r) => r.title).join(', ')}
                </Text>
              </div>
            </Group>
          ))}
        </Group>
      </Card>
      {children.length > 0 && (
        <Box
          pl="lg"
          style={{
            borderLeft: '2px solid var(--mantine-color-default-border)',
          }}
        >
          <Stack gap="xs">
            {children.map((child) => (
              <TeamCard key={child.id} team={child} byParent={byParent} mine={mine} />
            ))}
          </Stack>
        </Box>
      )}
    </Stack>
  )
}

export function TeamsPage() {
  const { user } = useAuth()
  const teams = useQuery({
    queryKey: ['teams'],
    queryFn: () => api<Team[]>('/teams/'),
  })

  if (teams.isLoading) return <Loader />
  const list = teams.data ?? []
  const ids = new Set(list.map((t) => t.id))
  const byParent = new Map<number | null, Team[]>()
  for (const team of list) {
    // Вышестоящая команда может быть неактивной — тогда показываем ветку от корня
    const key = team.parent !== null && ids.has(team.parent) ? team.parent : null
    byParent.set(key, [...(byParent.get(key) ?? []), team])
  }

  return (
    <Stack>
      <Title order={3}>Команды и командная вертикаль</Title>
      {user?.team && (
        <Card withBorder radius="md" padding="sm">
          <Text size="sm" c="dimmed" mb={4}>
            Эскалация по вашим инцидентам, если смена не отреагировала вовремя
          </Text>
          <Breadcrumbs separator={<IconArrowUp size={14} style={{ transform: 'rotate(90deg)' }} />}>
            {[user.team, ...user.command_chain].map((t) => (
              <Badge key={t.id} variant="light" color={KIND_COLOR[t.kind]}>
                {t.name}
              </Badge>
            ))}
          </Breadcrumbs>
        </Card>
      )}
      {list.length === 0 ? (
        <Alert icon={<IconInfoCircle />} color="gray">
          Команды ещё не созданы. Их заводит администратор в разделе «Администрирование → Команды».
        </Alert>
      ) : (
        (byParent.get(null) ?? []).map((team) => (
          <TeamCard key={team.id} team={team} byParent={byParent} mine={user?.team?.id} />
        ))
      )}
    </Stack>
  )
}
