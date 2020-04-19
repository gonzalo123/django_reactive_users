import boto3
from django.conf import settings

if settings.AWS_PROFILE:
    boto3.setup_default_session(profile_name=settings.AWS_PROFILE)
