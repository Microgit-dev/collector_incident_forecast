import {
  Alert,
  Anchor,
  Badge,
  Button,
  Card,
  Code,
  Grid,
  Group,
  List,
  NavLink,
  Stack,
  Table,
  Text,
  TextInput,
  Title,
} from '@mantine/core'
import { useDebouncedValue, useMediaQuery } from '@mantine/hooks'
import { IconArrowLeft, IconBook, IconEdit, IconSearch } from '@tabler/icons-react'
import { useQuery } from '@tanstack/react-query'
import dayjs from 'dayjs'
import { useState } from 'react'
import Markdown, { type Components } from 'react-markdown'
import { Link, useParams } from 'react-router-dom'
import remarkGfm from 'remark-gfm'

import { openAdmin } from '../api/admin'
import { api } from '../api/client'
import { ROLE } from '../api/labels'
import type { WikiArticle, WikiIndex } from '../api/types'

// Markdown из админки — в компоненты интерфейса; внутренние ссылки открываются без перезагрузки
const MD: Components = {
  h1: ({ children }) => (
    <Title order={2} mb="sm">
      {children}
    </Title>
  ),
  h2: ({ children }) => (
    <Title order={3} mt="lg" mb="xs">
      {children}
    </Title>
  ),
  h3: ({ children }) => (
    <Title order={4} mt="md" mb="xs">
      {children}
    </Title>
  ),
  p: ({ children }) => (
    <Text mb="sm" style={{ lineHeight: 1.6 }}>
      {children}
    </Text>
  ),
  a: ({ href, children }) =>
    href?.startsWith('/') ? (
      <Anchor component={Link} to={href}>
        {children}
      </Anchor>
    ) : (
      <Anchor href={href} target="_blank" rel="noreferrer">
        {children}
      </Anchor>
    ),
  ul: ({ children }) => (
    <List mb="sm" spacing={4}>
      {children}
    </List>
  ),
  ol: ({ children }) => (
    <List type="ordered" mb="sm" spacing={4}>
      {children}
    </List>
  ),
  li: ({ children }) => <List.Item>{children}</List.Item>,
  blockquote: ({ children }) => (
    <Alert variant="light" color="blue" mb="sm" styles={{ message: { fontSize: 'var(--mantine-font-size-sm)' } }}>
      {children}
    </Alert>
  ),
  code: ({ children }) => <Code>{children}</Code>,
  table: ({ children }) => (
    <Table.ScrollContainer minWidth={480} mb="sm">
      <Table striped withTableBorder>
        {children}
      </Table>
    </Table.ScrollContainer>
  ),
  thead: ({ children }) => <Table.Thead>{children}</Table.Thead>,
  tbody: ({ children }) => <Table.Tbody>{children}</Table.Tbody>,
  tr: ({ children }) => <Table.Tr>{children}</Table.Tr>,
  th: ({ children }) => <Table.Th>{children}</Table.Th>,
  td: ({ children }) => <Table.Td>{children}</Table.Td>,
}

function Contents({ index, slug }: { index?: WikiIndex; slug?: string }) {
  return (
    <Stack gap="md">
      {index?.sections.map((s) => (
        <div key={s.slug}>
          <Text size="xs" fw={700} c="dimmed" tt="uppercase" mb={4}>
            {s.title}
          </Text>
          {s.pages.map((p) => (
            <NavLink
              key={p.slug}
              component={Link}
              to={`/wiki/${p.slug}`}
              label={p.title}
              description={p.summary}
              active={p.slug === slug}
              rightSection={
                !p.is_published ? (
                  <Badge size="xs" color="gray">
                    черновик
                  </Badge>
                ) : undefined
              }
            />
          ))}
        </div>
      ))}
      {index && !index.sections.length && (
        <Text size="sm" c="dimmed">
          Ничего не найдено.
        </Text>
      )}
    </Stack>
  )
}

/** Вики для сотрудников: регламенты, памятки по ролям, справка. Статьи правятся в админке. */
export function WikiPage() {
  const { slug } = useParams()
  const mobile = useMediaQuery('(max-width: 48em)')
  const [q, setQ] = useState('')
  const [query] = useDebouncedValue(q.trim(), 250)
  const index = useQuery({
    queryKey: ['wiki', query],
    queryFn: () => api<WikiIndex>('/wiki/', { query: { q: query } }),
  })
  const first = index.data?.sections[0]?.pages[0]?.slug
  const current = slug ?? (mobile ? undefined : first)
  const page = useQuery({
    queryKey: ['wiki', 'page', current],
    queryFn: () => api<WikiArticle>(`/wiki/${current}/`),
    enabled: Boolean(current),
  })

  const toc = (
    <Stack gap="sm">
      <TextInput
        placeholder="Поиск по вики"
        leftSection={<IconSearch size={16} />}
        value={q}
        onChange={(e) => setQ(e.currentTarget.value)}
      />
      <Contents index={index.data} slug={current} />
    </Stack>
  )

  const article = page.data && (
    <Card withBorder radius="md" p={{ base: 'md', sm: 'xl' }}>
      <Group justify="space-between" mb="xs" wrap="wrap" gap="xs">
        <Group gap="xs">
          <Badge variant="light">{page.data.section}</Badge>
          {page.data.roles.length > 0 && (
            <Text size="xs" c="dimmed">
              для: {page.data.roles.map((r) => ROLE[r] ?? r).join(', ')}
            </Text>
          )}
        </Group>
        {index.data?.can_edit && (
          <Button
            // правка — в админке основной системы (вики одна на платформу), тем же входом
            onClick={() => void openAdmin(`wiki/wikipage/${page.data!.id}/change/`, 'combat')}
            size="compact-sm"
            variant="default"
            leftSection={<IconEdit size={14} />}
          >
            Редактировать
          </Button>
        )}
      </Group>
      <Markdown remarkPlugins={[remarkGfm]} components={MD}>
        {page.data.body}
      </Markdown>
      <Text size="xs" c="dimmed" mt="lg">
        Изменена {dayjs(page.data.updated_at).format('DD.MM.YYYY HH:mm')}
        {page.data.updated_by && ` · ${page.data.updated_by}`}
      </Text>
    </Card>
  )

  if (mobile) {
    return (
      <Stack>
        {slug ? (
          <>
            <Anchor component={Link} to="/wiki" size="sm">
              <Group gap={4}>
                <IconArrowLeft size={14} /> Оглавление
              </Group>
            </Anchor>
            {article}
          </>
        ) : (
          <>
            <Group gap="xs">
              <IconBook size={22} />
              <Title order={3}>Вики</Title>
            </Group>
            {toc}
          </>
        )}
      </Stack>
    )
  }

  return (
    <Stack>
      <Group gap="xs">
        <IconBook size={22} />
        <Title order={3}>Вики</Title>
      </Group>
      <Grid gap="lg">
        <Grid.Col span={{ base: 12, md: 4, lg: 3 }}>{toc}</Grid.Col>
        <Grid.Col span={{ base: 12, md: 8, lg: 9 }}>{article}</Grid.Col>
      </Grid>
    </Stack>
  )
}
