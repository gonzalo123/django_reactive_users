from django.contrib.auth.models import User
from django.db.models.signals import pre_save, post_save, post_delete
from django.dispatch import receiver
from master.serializers import UserSerializer
from master.tasks import user_changed_event, Actions


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
