"""
URL configuration for smartHomeSite project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.conf.urls.i18n import i18n_patterns
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import path, include

from .views import redirect_view

urlpatterns = i18n_patterns(
    path('', redirect_view, {'target': 'devices/'}),
    # Logowanie i wylogowanie (tylko POST) z django.contrib.auth – bez rejestracji
    # i resetu hasła. Szablon: templates/registration/login.html.
    path('login/', auth_views.LoginView.as_view(redirect_authenticated_user=True), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('devices/', include('devices.urls')),
    path('admin/', admin.site.urls),
)
