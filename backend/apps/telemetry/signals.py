from django.dispatch import Signal

# kwargs: changes: list[StateChange]. Подписчики — правила инцидентов, уведомления, метрики.
# Сигнал развязывает модули: телеметрия не знает, кто реагирует на смену состояния.
channel_states_changed = Signal()
