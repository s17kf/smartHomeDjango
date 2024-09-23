from simple_menu import Menu, MenuItem
from django.utils.translation import gettext_lazy as _
from django.urls import reverse_lazy

Menu.add_item("main", MenuItem(_("Locations"),
                               reverse_lazy("devices:location_list"),
                               icon="menu-app", ))
Menu.add_item("main", MenuItem(_("Favourites"),
                               reverse_lazy("devices:favourites"),
                               icon="menu-app", ))
