from django.urls import path

from .views import forecast, update_table

urlpatterns = [
    path("forecast/", forecast, name='forecast'),
    path("update-table/", update_table, name='update-table')
]