## Django reactive users with Celery and Channels


Today I want to build a prototype. The idea is to create two Django applications. One application will be the master and the other one will the client. Both applications will have their User model but each change within master User model will be propagated through the client (or clients). Let me show you what I've got in my mind:

We're going to create one signal in User model (at Master) to detect user modifications:
* If certain fields have been changed (for example we're going to ignore last_login, password and things like that) we're going to emit a event
* I normally work with AWS, so the event will be a SNS event.
* The idea to have multiple clients, so each client will be listening to one SQS queue. Those SQSs queues will be mapped to the SNS event.
* To decouple the SNS sending og the message we're going to send it via Celery worker.
* The second application (the Client) will have one listener to the SQS queue. 
* Each time the listener have a message it will persists the user information within the client's User model 
* And also it will emit on message to one Django Channel's consumer to be sent via websockets to the browser.

### The Master

We're going to emit the event each time the User model changes (and also when we create or delete one user). To detect changes we're going to register on signal in the pre_save to mark if the model has been changed and later in the post_save we're going to emit the event via Celery worker.

```python
@receiver(pre_save, sender=User)
def pre_user_modified(sender, instance, **kwargs):
    instance.is_modified = None

    if instance.is_staff is False and instance.id is not None:
        modified_user_data = UserSerializer(instance).data
        user = User.objects.get(username=modified_user_data['username'])
        user_serializer_data = UserSerializer(user).data

        if user_serializer_data != modified_user_data:
            instance.is_modified = True


@receiver(post_save, sender=User)
def post_user_modified(sender, instance, created, **kwargs):
    if instance.is_staff is False:
        if created or instance.is_modified:
            modified_user_data = UserSerializer(instance).data
            user_changed_event.delay(modified_user_data, action=Actions.INSERT if created else Actions.UPDATE)


@receiver(post_delete, sender=User)
def post_user_deleted(sender, instance, **kwargs):
    deleted_user_data = UserSerializer(instance).data
    user_changed_event.delay(deleted_user_data, action=Actions.DELETE)
```

We need to register our signals in apps.py
```python
from django.apps import AppConfig


class MasterConfig(AppConfig):
    name = 'master'

    def ready(self):
        from master.signals import pre_user_modified
        from master.signals import post_user_modified
        from master.signals import post_user_deleted
```

Our Celery task will send the message to sns queue
```python
@shared_task()
def user_changed_event(body, action):
    sns = boto3.client('sns')
    message = {
        "user": body,
        "action": action
    }
    response = sns.publish(
        TargetArn=settings.SNS_REACTIVE_TABLE_ARN,
        Message=json.dumps({'default': json.dumps(message)}),
        MessageStructure='json'
    )
    logger.info(response)
```

### AWS
In Aws We need to create one SNS messaging service and one SQS queue linked to this SNS.

### The Client

First we need one command to run the listener.
```python
class Actions:
    INSERT = 0
    UPDATE = 1
    DELETE = 2

switch_actions = {
    Actions.INSERT: insert_user,
    Actions.UPDATE: update_user,
    Actions.DELETE: delete_user,
}

class Command(BaseCommand):
    help = 'sqs listener'

    def handle(self, *args, **options):
        self.stdout.write(self.style.WARNING("starting listener"))
        sqs = boto3.client('sqs')

        queue_url = settings.SQS_REACTIVE_TABLES

        def process_message(message):
            decoded_body = json.loads(message['Body'])
            data = json.loads(decoded_body['Message'])

            switch_actions.get(data['action'])(
                data=data['user'],
                timestamp=message['Attributes']['SentTimestamp']
            )

            notify_to_user(data['user'])

            sqs.delete_message(
                QueueUrl=queue_url,
                ReceiptHandle=message['ReceiptHandle'])

        def loop():
            response = sqs.receive_message(
                QueueUrl=queue_url,
                AttributeNames=[
                    'SentTimestamp'
                ],
                MaxNumberOfMessages=10,
                MessageAttributeNames=[
                    'All'
                ],
                WaitTimeSeconds=20
            )

            if 'Messages' in response:
                messages = [message for message in response['Messages'] if 'Body' in message]
                [process_message(message) for message in messages]

        try:
            while True:
                loop()
        except KeyboardInterrupt:
            sys.exit(0)
```

Here we persists the model in Client's database

```python
def insert_user(data, timestamp):
    username = data['username']
    serialized_user = UserSerializer(data=data)
    serialized_user.create(validated_data=data)
    logging.info(f"user: {username} created at {timestamp}")


def update_user(data, timestamp):
    username = data['username']
    try:
        user = User.objects.get(username=data['username'])
        serialized_user = UserSerializer(user)
        serialized_user.update(user, data)
        logging.info(f"user: {username} updated at {timestamp}")
    except User.DoesNotExist:
        logging.info(f"user: {username} don't exits. Creating ...")
        insert_user(data, timestamp)


def delete_user(data, timestamp):
    username = data['username']
    try:
        user = User.objects.get(username=username)
        user.delete()
        logging.info(f"user: {username} deleted at {timestamp}")
    except User.DoesNotExist:
        logging.info(f"user: {username} don't exits. Don't deleted")
```

And also emit one message to channel's consumer

```python
def notify_to_user(user):
    username = user['username']
    serialized_user = UserSerializer(user)
    emit_message_to_user(
        message=serialized_user.data,
        username=username, )
```

Here the Consumer:
```python
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
```

Our consumer will only allow to connect only if the user is authenticated. That's because I like Django Channels. This kind of thing are really simple to to (I've done similar things using PHP applications connected to a socket.io server and it was a nightmare). I've created a couple of decorators to ensure authentication in the consumer.

```python
def personal_consumer(func):
    @wraps(func)
    async def wrapper_decorator(*args, **kwargs):
        self = args[0]

        async def accept():
            value = await func(*args, **kwargs)
            await self.accept()
            return value

        if self.scope['user'].is_authenticated:
            username = self.scope['user'].username
            room_name = self.scope['url_route']['kwargs']['username']
            if username == room_name:
                return await accept()

        await self.close()

    return wrapper_decorator


def private_consumer_event(func):
    @wraps(func)
    async def wrapper_decorator(*args, **kwargs):
        self = args[0]
        if self.scope['user'].is_authenticated:
            return await func(*args, **kwargs)

    return wrapper_decorator
```

That's the websocket route
```python
from django.urls import re_path

from client import consumers

websocket_urlpatterns = [
    re_path(r'ws/(?P<username>\w+)$', consumers.WsConsumer),
]
```

Finally we only need to connect our HTML page to the websocket
```jinja2
{% extends "base.html" %}

{% block title %}Example{% endblock %}
{% block header_text %}Hello <span id="name">{{ request.user.first_name }}</span>{% endblock %}

{% block extra_body %}
  <script>
    var ws_scheme = window.location.protocol === "https:" ? "wss" : "ws"
    var ws_path = ws_scheme + '://' + window.location.host + "/ws/{{ request.user.username }}"
    var ws = new ReconnectingWebSocket(ws_path)
    var render = function (key, value) {
      document.querySelector(`#${key}`).innerHTML = value
    }
    ws.onmessage = function (e) {
      const data = JSON.parse(e.data);
      render('name', data.first_name)
    }

    ws.onopen = function () {
      console.log('Connected')
    };
  </script>
{% endblock %}
```

Here a docker-compose with the project:

```yaml
version: '3.4'

services:
  redis:
    image: redis
  master:
    image: reactive_master:latest
    command: python manage.py runserver 0.0.0.0:8001
    build:
      context: ./master
      dockerfile: Dockerfile
    depends_on:
      - "redis"
    ports:
      - 8001:8001
    environment:
      REDIS_HOST: redis
  celery:
    image: reactive_master:latest
    command: celery -A master worker --uid=nobody --gid=nogroup
    depends_on:
      - "redis"
      - "master"
    environment:
      REDIS_HOST: redis
      SNS_REACTIVE_TABLE_ARN: ${SNS_REACTIVE_TABLE_ARN}
      AWS_DEFAULT_REGION: ${AWS_DEFAULT_REGION}
      AWS_ACCESS_KEY_ID: ${AWS_ACCESS_KEY_ID}
      AWS_SECRET_ACCESS_KEY: ${AWS_SECRET_ACCESS_KEY}
  client:
    image: reactive_client:latest
    command: python manage.py runserver 0.0.0.0:8000
    build:
      context: ./client
      dockerfile: Dockerfile
    depends_on:
      - "redis"
    ports:
      - 8000:8000
    environment:
      REDIS_HOST: redis
  listener:
    image: reactive_client:latest
    command: python manage.py listener
    build:
      context: ./client
      dockerfile: Dockerfile
    depends_on:
      - "redis"
    environment:
      REDIS_HOST: redis
      SQS_REACTIVE_TABLES: ${SQS_REACTIVE_TABLES}
      AWS_DEFAULT_REGION: ${AWS_DEFAULT_REGION}
      AWS_ACCESS_KEY_ID: ${AWS_ACCESS_KEY_ID}
      AWS_SECRET_ACCESS_KEY: ${AWS_SECRET_ACCESS_KEY}
```

And that's all. Here a working example of the prototype in action:

[![Alt text](https://img.youtube.com/vi/HTeou98z7fw/0.jpg)](https://www.youtube.com/watch?v=HTeou98z7fw)
