from django.contrib import admin
from django.urls import path, include
from client.views import index

urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/', include("django.contrib.auth.urls")),
    path('', index)
]
