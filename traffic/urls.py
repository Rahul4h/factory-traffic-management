from django.urls import path
from . import views

urlpatterns = [
    path('', views.dashboard),
    path('api/junctions', views.list_junctions),
    path('api/junctions/create', views.create_junction),
    path('api/junctions/<str:jid>', views.get_junction),
    path('api/junctions/<str:jid>/status', views.junction_status),
    path('api/junctions/<str:jid>/commands', views.junction_command),
    path('api/junctions/<str:jid>/history', views.junction_history),
    path('api/sensor-events', views.sensor_event),
    path('api/controller-events', views.controller_event),
]
