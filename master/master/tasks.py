from enum import Enum

from celery import shared_task
import logging
from django.conf import settings
import boto3
import json

logger = logging.getLogger(__name__)

class Actions:
    INSERT = 0
    UPDATE = 1
    DELETE = 2


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
