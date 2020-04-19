from django.apps import AppConfig


class MasterConfig(AppConfig):
    name = 'master'

    def ready(self):
        from master.signals import pre_user_modified
        from master.signals import post_user_modified
        from master.signals import post_user_deleted
