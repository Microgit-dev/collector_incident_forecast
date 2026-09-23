from channels.generic.websocket import AsyncJsonWebsocketConsumer

from .services import user_group


class NotificationConsumer(AsyncJsonWebsocketConsumer):
    """ws/notifications/?token=<JWT> — персональный поток уведомлений пользователя."""

    async def connect(self):
        user = self.scope.get("user")
        if not user or not user.is_authenticated:
            await self.close(code=4401)
            return
        self.group = user_group(user.pk)
        await self.channel_layer.group_add(self.group, self.channel_name)
        await self.accept()

    async def disconnect(self, code):
        if hasattr(self, "group"):
            await self.channel_layer.group_discard(self.group, self.channel_name)

    async def notification_push(self, event):
        await self.send_json({"type": "notification", "data": event["notification"]})
