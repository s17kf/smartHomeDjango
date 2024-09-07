from django.urls import path

from . import views

app_name = 'devices'
urlpatterns = [
    path('', views.IndexView.as_view(), name='index'),
    path('location/<int:location_id>/', views.LocationView.as_view(), name='location'),
    path('device/<int:pk>/', views.DeviceView.as_view(), name='device'),
    path('location_update/<int:location_id>', views.location_update, name='location_update'),
    path('relay_update/<int:device_id>', views.relay_update, name='relay_update'),
    path('periodic_relay_manual_activate/<int:device_id>', views.periodic_relay_manual_activate,
         name='periodic_relay_manual_activate'),
    path('periodic_relay_manual_deactivate/<int:device_id>', views.periodic_relay_manual_deactivate,
         name='periodic_relay_manual_deactivate'),
    path('periodic_relay_add_active_day/<int:device_id>', views.periodic_relay_add_active_day,
         name='periodic_relay_add_active_day'),
    path('periodic_relay_remove_active_day/<int:device_id>', views.periodic_relay_remove_active_day,
         name='periodic_relay_remove_active_day'),
    path('periodic_relay_add_active_period/<int:device_id>', views.periodic_relay_add_active_period,
         name='periodic_relay_add_active_period'),
    path('periodic_relay_remove_active_period/<int:device_id>', views.periodic_relay_remove_active_period,
         name='periodic_relay_remove_active_period'),
]
