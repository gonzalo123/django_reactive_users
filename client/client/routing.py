from django.urls import re_path

from client import consumers

websocket_urlpatterns = [
    re_path(r'ws/(?P<username>\w+)$', consumers.WsConsumer),
]
