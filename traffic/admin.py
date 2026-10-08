from django.contrib import admin
from .models import Junction, JunctionState, History, QueueEntry, ProcessedEvent

@admin.register(Junction)
class JunctionAdmin(admin.ModelAdmin):
    list_display = ('id', 'created_at')

admin.site.register([JunctionState, History, QueueEntry, ProcessedEvent])
