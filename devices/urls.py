from django.urls import path

from . import views
from smartHomeSite.views import redirect_view

app_name = 'devices'
urlpatterns = [
    path('', redirect_view, {'target': 'locations/'}, name='main'),
    path('locations/', views.LocationListView.as_view(), name='location_list'),
    path('location/<int:location_id>/', views.location, name='location'),
    path('favourites/', views.FavouritesView.as_view(), name='favourites'),
    path('events/', views.device_events, name='events'),
    path('device/<slug:slug>/', views.device, name='device'),
    path('device/<slug:slug>/card/', views.device_card, name='device_card'),
    path('device/<slug:slug>/set/', views.device_set, name='device_set'),
    path('device/<slug:slug>/override/', views.device_override, name='device_override'),
    path('rules/', views.rule_list, name='rule_list'),
    path('rules/new/', views.rule_form, name='rule_new'),
    path('rules/state-fields/', views.rule_state_fields, name='rule_state_fields'),
    path('rules/<int:pk>/edit/', views.rule_form, name='rule_edit'),
    path('rules/<int:pk>/toggle/', views.rule_toggle, name='rule_toggle'),
    path('rules/<int:pk>/delete/', views.rule_delete, name='rule_delete'),
]
