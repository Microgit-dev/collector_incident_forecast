/**
 * Отметка «Выполнена» бригадой: короткий отчёт и фактическое состояние оборудования заявки.
 * Состояние уходит в реестр (последний осмотр), работа по ТО обновляет дату обслуживания.
 */
import { Button, Group, Loader, Modal, SegmentedControl, Stack, Text, Textarea } from '@mantine/core'
import { notifications } from '@mantine/notifications'
import { useMutation, useQuery } from '@tanstack/react-query'
import { useState } from 'react'

import { api } from '../api/client'
import { CONDITION } from '../api/labels'

interface OrderBrief {
  id: number
  number: string
  title: string
  equipment: number | null
  equipment_name: string | null
}

function CompleteForm({ id, onClose, onDone }: { id: number; onClose: () => void; onDone: () => void }) {
  const [report, setReport] = useState('')
  const [condition, setCondition] = useState('')
  const [notes, setNotes] = useState('')
  const order = useQuery({ queryKey: ['workorder', id], queryFn: () => api<OrderBrief>(`/workorders/items/${id}/`) })
  const save = useMutation({
    mutationFn: () =>
      api(`/workorders/items/${id}/transition/`, {
        method: 'POST',
        body: { status: 'done', report, condition, notes },
      }),
    onSuccess: () => {
      notifications.show({ color: 'teal', message: `Заявка ${order.data?.number ?? ''} выполнена` })
      onDone()
      onClose()
    },
    onError: (e) => notifications.show({ color: 'red', message: e.message }),
  })
  if (order.isLoading || !order.data) return <Loader size="sm" />
  const needsCondition = Boolean(order.data.equipment)
  return (
    <Stack>
      <Text size="sm">{order.data.title}</Text>
      <Textarea
        label="Что сделано"
        placeholder="Например: насосы обслужены, поплавок заменён"
        autosize
        minRows={2}
        value={report}
        onChange={(e) => setReport(e.currentTarget.value)}
      />
      {needsCondition && (
        <Stack gap={4}>
          <Text size="sm" fw={500}>
            Состояние оборудования после работ: {order.data.equipment_name}
          </Text>
          <SegmentedControl
            fullWidth
            orientation="vertical"
            value={condition}
            onChange={setCondition}
            data={Object.entries(CONDITION).map(([value, c]) => ({ value, label: c.label }))}
          />
          <Textarea
            placeholder="Замечания (что требует ремонта)"
            autosize
            minRows={1}
            value={notes}
            onChange={(e) => setNotes(e.currentTarget.value)}
          />
          <Text size="xs" c="dimmed">
            Состояние попадёт в реестр оборудования; «требует ремонта» и «неисправно» инженер ТО увидит в плане.
          </Text>
        </Stack>
      )}
      <Group justify="flex-end">
        <Button variant="default" onClick={onClose}>
          Отмена
        </Button>
        <Button
          size="md"
          loading={save.isPending}
          disabled={needsCondition && !condition}
          onClick={() => save.mutate()}
        >
          Выполнена
        </Button>
      </Group>
    </Stack>
  )
}

/** Модалка выполнения: open(id) — открыть для заявки, modal — вставить в разметку страницы. */
export function useCompleteOrder(onDone: () => void) {
  const [id, setId] = useState<number | null>(null)
  const modal = (
    <Modal opened={id !== null} onClose={() => setId(null)} title="Отметить выполнение" fullScreen={false} size="md">
      {id !== null && <CompleteForm id={id} onClose={() => setId(null)} onDone={onDone} />}
    </Modal>
  )
  return { open: setId, modal }
}
