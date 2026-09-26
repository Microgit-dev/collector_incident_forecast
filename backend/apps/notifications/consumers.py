from channels.generic.websocket import AsyncJsonWebsocketConsumer

from .auth import SUBPROTOCOL
from .services import user_group


class NotificationConsumer(AsyncJsonWebsocketConsumer):
    """ws/notifications/ (протоколы ["jwt", <токен>]) — персональный поток уведомлений пользователя."""

    async def connect(self):
        user = self.scope.get("user")
        if not user or not user.is_authenticated:
            await self.close(code=4401)
            return
        self.group = user_group(user.pk)
        await self.channel_layer.group_add(self.group, self.channel_name)
        # сервер обязан подтвердить один из предложенных протоколов — «jwt», сам токен не возвращается
        await self.accept(subprotocol=SUBPROTOCOL)

    async def disconnect(self, code):
        if hasattr(self, "group"):
            await self.channel_layer.group_discard(self.group, self.channel_name)

    async def notification_push(self, event):
        await self.send_json({"type": "notification", "data": event["notification"]})

    async def incident_update(self, event):
        await self.send_json({"type": "incident", "data": event["event"]})
