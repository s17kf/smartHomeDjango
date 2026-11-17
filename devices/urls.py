from django.urls import path

from . import views
from smartHomeSite.views import redirect_view

app_name = 'devices'
urlpatterns = [
    path('', redirect_view, {'target': 'locations/'}, name='main'),
    path('locations/', views.LocationListView.as_view(), name='location_list'),
    path('location/<int:location_id>/', views.location, name='location'),
    path('location/<int:location_id>/cards/', views.location_cards, name='location_cards'),
    path('favourites/', views.FavouritesView.as_view(), name='favourites'),
    path('device/<slug:slug>/', views.device, name='device'),
    path('device/<slug:slug>/card/', views.device_card, name='device_card'),
    path('device/<slug:slug>/set/', views.device_set, name='device_set'),
]
