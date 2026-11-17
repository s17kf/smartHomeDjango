from django.urls import path

from . import views
from smartHomeSite.views import redirect_view

app_name = 'devices'
urlpatterns = [
    path('', redirect_view, {'target': 'locations/'}, name='main'),
    path('locations/', views.LocationListView.as_view(), name='location_list'),
    path('location/<int:location_id>/', views.LocationView.as_view(), name='location'),
    path('favourites/', views.FavouritesView.as_view(), name='favourites'),
    path('device/<int:pk>/', views.DeviceView.as_view(), name='device'),
]
