from django.urls import path

from . import views

app_name = 'devices'
urlpatterns = [
    path('', views.index, name='index'),
    path('location/<int:location_id>/', views.location, name='location'),
    path('device/<int:device_id>/', views.device_details, name='device'),
    path('location_update/<int:location_id>', views.location_update, name='location_update'),
]
