import { Alert, Badge, Button, Card, Group, Loader, SimpleGrid, Stack, Table, Text, Title, Tooltip } from '@mantine/core'
import { notifications } from '@mantine/notifications'
import { IconCheck, IconExternalLink, IconInfoCircle, IconSettings } from '@tabler/icons-react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'

import { openAdmin } from '../api/admin'
import { api } from '../api/client'
import type { Operation, OperationsMatrix } from '../api/types'
import { useAuth } from '../auth/AuthContext'
import { CONTOUR, contourHref } from '../contour'

// порядок столбцов матрицы — по командной вертикали
const ROLE_ORDER = ['head', 'ods_dispatcher', 'unit_dispatcher', 'analyst', 'maintenance_engineer', 'technician', 'observer', 'admin']

function admin(path: string, contour: Operation['contour']) {
  openAdmin(path, contour).catch((e: Error) => notifications.show({ color: 'red', message: e.message }))
}

function TaskCard({ op }: { op: Operation }) {
  const here = op.contour === CONTOUR
  return (
    <Card withBorder radius="md" padding="md">
      <Stack gap={6} h="100%">
        <Group justify="space-between" wrap="nowrap" align="flex-start">
          <Text fw={600}>{op.title}</Text>
          <Group gap={4} wrap="nowrap">
            {op.contour === 'training' && (
              <Badge size="xs" color="violet" variant="light">
                учебный контур
              </Badge>
            )}
            <Badge size="xs" variant="light" color={op.scope === 'зона' ? 'cyan' : 'gray'}>
              {op.scope === 'зона' ? 'своя зона' : 'весь район'}
            </Badge>
          </Group>
        </Group>
        <Text size="sm" c="dimmed" style={{ flex: 1 }}>
          {op.description}
        </Text>
        {!op.responsible && (
          <Text size="xs" c="dimmed">
            Доступно вам как администратору системы; отвечает за это другая роль.
          </Text>
        )}
        <Group gap="xs">
          {op.page &&
            (here ? (
              <Button component={Link} to={op.page} size="xs">
                Открыть
              </Button>
            ) : (
              <Button component="a" href={contourHref(op.contour, op.page)} size="xs" color="violet">
                Открыть
              </Button>
            ))}
          {op.admin && (
            <Button
              size="xs"
              variant="default"
              rightSection={<IconExternalLink size={14} />}
              onClick={() => admin(op.admin!, op.contour)}
            >
              В админке
            </Button>
          )}
        </Group>
      </Stack>
    </Card>
  )
}

/**
 * Администрирование: только задачи своей роли (вместо всех разделов админки сразу) и открытая всем
 * матрица «кто за что отвечает». Админка открывается отсюда тем же входом, без второго пароля.
 */
export function AdministrationPage() {
  const { user } = useAuth()
  const data = useQuery({
    queryKey: ['operations'],
    queryFn: () => api<OperationsMatrix>('/auth/operations/', { contour: 'combat' }),
    staleTime: 5 * 60_000,
  })
  const mine = user?.operations ?? []
  const roles = ROLE_ORDER.filter((r) => data.data?.roles[r])

  return (
    <Stack>
      <Group justify="space-between" wrap="wrap">
        <Title order={3}>Администрирование</Title>
        {user?.admin && (
          <Group gap="xs">
            <Button
              variant="default"
              size="xs"
              leftSection={<IconSettings size={16} />}
              onClick={() => admin('', 'combat')}
            >
              Админка платформы
            </Button>
            {mine.some((op) => op.contour === 'training') && (
              <Button
                variant="default"
                size="xs"
                color="violet"
                leftSection={<IconSettings size={16} />}
                onClick={() => admin('', 'training')}
              >
                Админка учебного контура
              </Button>
            )}
          </Group>
        )}
      </Group>
      <Text size="sm" c="dimmed">
        Здесь только задачи вашей роли. Разделы админки открываются тем же входом — второй пароль не нужен.
      </Text>

      {mine.length ? (
        <SimpleGrid cols={{ base: 1, sm: 2, lg: 3 }}>
          {mine.map((op) => (
            <TaskCard key={op.code} op={op} />
          ))}
        </SimpleGrid>
      ) : (
        <Alert icon={<IconInfoCircle size={18} />} color="gray">
          За вашей ролью нет административных операций. Кто отвечает за изменения — в таблице ниже.
        </Alert>
      )}

      <Card withBorder radius="md">
        <Title order={5} mb={4}>
          Кто за что отвечает
        </Title>
        <Text size="sm" c="dimmed" mb="sm">
          Администратор системы может выполнить любую операцию, но отвечает за пользователей, роли и интеграции. «Своя зона» —
          только в пределах зоны ответственности.
        </Text>
        {data.isLoading ? (
          <Loader size="sm" />
        ) : (
          <Table.ScrollContainer minWidth={820}>
            <Table striped withTableBorder verticalSpacing={6}>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>Операция</Table.Th>
                  {roles.map((r) => (
                    <Table.Th key={r} ta="center" style={{ fontSize: 12 }}>
                      {data.data!.roles[r]}
                    </Table.Th>
                  ))}
                  <Table.Th>Где</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {data.data?.matrix.map((op) => (
                  <Table.Tr key={op.code}>
                    <Table.Td>
                      <Tooltip label={op.description} multiline w={320}>
                        <Text size="sm">{op.title}</Text>
                      </Tooltip>
                    </Table.Td>
                    {roles.map((r) => {
                      const responsible = op.responsible.includes(r)
                      const owner = r === 'admin' && !responsible
                      return (
                        <Table.Td key={r} ta="center">
                          {(responsible || owner) && (
                            <IconCheck
                              size={16}
                              color={owner ? 'var(--mantine-color-dimmed)' : 'var(--mantine-color-teal-6)'}
                              aria-label={owner ? 'может выполнить' : 'отвечает'}
                            />
                          )}
                        </Table.Td>
                      )
                    })}
                    <Table.Td>
                      <Text size="xs" c="dimmed">
                        {op.contour === 'training' ? 'учебный контур' : 'основная система'} ·{' '}
                        {op.scope === 'зона' ? 'своя зона' : 'район'}
                      </Text>
                    </Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </Table.ScrollContainer>
        )}
      </Card>
    </Stack>
  )
}
