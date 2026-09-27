/** Загрузка выгрузки реестра оборудования заказчика (CSV/XLSX) с итогом и ошибками по строкам. */
import { Alert, Anchor, Button, Checkbox, FileButton, Group, List, Stack, Text } from '@mantine/core'
import { notifications } from '@mantine/notifications'
import { IconUpload } from '@tabler/icons-react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import { download, upload } from '../api/client'

interface ImportResult {
  rows: number
  created: number
  updated: number
  retired: number
  emulated_removed: number
  error_count: number
  errors: { row: number; inventory_number: string | null; error: string }[]
}

export function RegistryImport() {
  const client = useQueryClient()
  const [full, setFull] = useState(true)
  const [result, setResult] = useState<ImportResult | null>(null)
  const send = useMutation({
    mutationFn: (file: File) => {
      const form = new FormData()
      form.append('file', file)
      form.append('full', String(full))
      return upload<ImportResult>('/integrations/registry/import/', form)
    },
    onSuccess: (r) => {
      setResult(r)
      void client.invalidateQueries({ queryKey: ['equipment'] })
      void client.invalidateQueries({ queryKey: ['maintenance-plan'] })
      void client.invalidateQueries({ queryKey: ['integrations'] })
    },
    onError: (e) => notifications.show({ color: 'red', message: e.message }),
  })
  return (
    <Stack gap="xs">
      <Text size="sm">
        Выгрузка из учётной системы: CSV (разделитель «;» или «,», UTF-8 или Windows-1251) или XLSX. Ключ — инвентарный
        номер; записи, заведённые вручную, не перезаписываются.{' '}
        <Anchor
          size="sm"
          onClick={() => void download('/integrations/registry/import/', 'equipment_registry_template.csv')}
        >
          Шаблон файла
        </Anchor>
      </Text>
      <Group gap="md">
        <FileButton onChange={(f) => f && send.mutate(f)} accept=".csv,.xlsx">
          {(props) => (
            <Button {...props} size="xs" leftSection={<IconUpload size={14} />} loading={send.isPending}>
              Загрузить реестр
            </Button>
          )}
        </FileButton>
        <Checkbox
          size="xs"
          checked={full}
          onChange={(e) => setFull(e.currentTarget.checked)}
          label="Полный реестр: единицы, которых нет в файле, — выведены из эксплуатации"
        />
      </Group>
      {result && (
        <Alert color={result.error_count ? 'yellow' : 'teal'} variant="light">
          <Text size="sm">
            Строк {result.rows}: добавлено {result.created}, обновлено {result.updated}, выведено {result.retired}
            {result.emulated_removed ? `, эмуляция заменена (${result.emulated_removed})` : ''}; ошибок{' '}
            {result.error_count}.
          </Text>
          {result.errors.length > 0 && (
            <List size="xs" mt={4}>
              {result.errors.slice(0, 10).map((e) => (
                <List.Item key={e.row}>
                  строка {e.row} {e.inventory_number && `(${e.inventory_number})`}: {e.error}
                </List.Item>
              ))}
            </List>
          )}
        </Alert>
      )}
    </Stack>
  )
}
