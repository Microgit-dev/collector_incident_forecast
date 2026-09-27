import { Alert, Button, Center, Paper, PasswordInput, Stack, Text, TextInput, Title } from '@mantine/core'
import { useEffect, useState, type FormEvent } from 'react'
import { Navigate, useNavigate, useSearchParams } from 'react-router-dom'

import { returnTo } from '../api/admin'
import { useAuth } from '../auth/AuthContext'
import { BASE, loginHref, safeNext } from '../contour'

/**
 * Единственная страница входа платформы (в корне). Учебный контур и админка своих форм входа не имеют:
 * они присылают сюда с ?next=, а после входа (или сразу, если вход уже выполнен) возвращаем обратно.
 */
function leavesThisApp(next: string): boolean {
  // другая подсистема или админка — полная загрузка страницы, не переход внутри приложения
  return next.startsWith('/training') || next.startsWith('/admin/')
}

export function LoginPage() {
  const { user, login } = useAuth()
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const next = safeNext(params.get('next'))
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [pending, setPending] = useState(false)

  useEffect(() => {
    // в подсистеме своей формы нет — вход в основной системе с возвратом сюда
    if (BASE) window.location.replace(loginHref(`${BASE}/`))
    else if (user && next && leavesThisApp(next)) void returnTo(next)
  }, [user, next])

  if (BASE || (user && next && leavesThisApp(next))) return null
  if (user) return <Navigate to={next ?? '/'} replace />

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    setPending(true)
    setError(null)
    try {
      await login(username, password)
      if (next && leavesThisApp(next)) await returnTo(next)
      else navigate(next ?? '/', { replace: true })
    } catch {
      setError('Неверный логин или пароль')
    } finally {
      setPending(false)
    }
  }

  return (
    <Center mih="100vh" p="md">
      <Paper withBorder shadow="sm" p="xl" radius="md" w="100%" maw={380}>
        <form onSubmit={submit}>
          <Stack>
            <div>
              <Title order={3}>Прогноз инцидентов</Title>
              <Text size="sm" c="dimmed">
                Инженерные коллекторы · вход по учётной записи домена
              </Text>
            </div>
            {error && <Alert color="red">{error}</Alert>}
            <TextInput label="Логин" value={username} onChange={(e) => setUsername(e.currentTarget.value)} required autoFocus />
            <PasswordInput label="Пароль" value={password} onChange={(e) => setPassword(e.currentTarget.value)} required />
            <Button type="submit" loading={pending}>
              Войти
            </Button>
          </Stack>
        </form>
      </Paper>
    </Center>
  )
}
