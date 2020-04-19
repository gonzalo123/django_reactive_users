from django.contrib.auth.models import User
from rest_framework import serializers


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        exclude = (
            'password', 'last_login', 'is_superuser',
            'is_staff', 'is_active', 'date_joined'
        )
        depth = 1
