from .celery import app as celery_app

default_app_config = 'master.apps.MasterConfig'
__all__ = ['celery_app']
