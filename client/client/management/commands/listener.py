from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
import logging
from django.conf import settings
import sys
import boto3
import json

from client.consumers import WsConsumer, emit_message_to_user
from client.serializers import UserSerializer

logger = logging.getLogger(__name__)


class Actions:
    INSERT = 0
    UPDATE = 1
    DELETE = 2


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


switch_actions = {
    Actions.INSERT: insert_user,
    Actions.UPDATE: update_user,
    Actions.DELETE: delete_user,
}


def notify_to_user(user):
    username = user['username']
    serialized_user = UserSerializer(user)
    emit_message_to_user(
        message=serialized_user.data,
        username=username, )


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
