import { Alert, Button, Center, Paper, PasswordInput, Stack, Text, TextInput, Title } from '@mantine/core'
import { useState, type FormEvent } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'

import { useAuth } from '../auth/AuthContext'

export function LoginPage() {
  const { user, login } = useAuth()
  const navigate = useNavigate()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [pending, setPending] = useState(false)

  if (user) return <Navigate to="/" replace />

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    setPending(true)
    setError(null)
    try {
      await login(username, password)
      navigate('/', { replace: true })
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
