from asgiref.sync import async_to_sync
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.layers import get_channel_layer
import json
from client.channels import private_consumer_event, personal_consumer


class WsConsumer(AsyncWebsocketConsumer):
    @personal_consumer
    async def connect(self):
        await self.channel_layer.group_add(
            self._get_personal_room(),
            self.channel_name
        )

    @private_consumer_event
    async def emit_message(self, event):
        message = event['message']
        await self.send(text_data=json.dumps(message))

    def _get_personal_room(self):
        username = self.scope['user'].username
        return self.get_room_name(username)

    @staticmethod
    def get_room_name(room):
        return f"{'ws_room'}_{room}"


def emit_message_to_user(message, username):
    group = WsConsumer.get_room_name(username)
    channel_layer = get_channel_layer()
    async_to_sync(channel_layer.group_send)(group, {
        'type': WsConsumer.emit_message.__name__,
        'message': message
    })
