from django.db import models


class Junction(models.Model):
    id = models.CharField(primary_key=True, max_length=10)
    config = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)


class ProcessedEvent(models.Model):
    event_id = models.CharField(primary_key=True, max_length=100)
    received_at = models.DateTimeField(auto_now_add=True)


class QueueEntry(models.Model):
    junction = models.ForeignKey(Junction, on_delete=models.CASCADE)
    direction = models.CharField(max_length=10)
    vehicle_id = models.CharField(max_length=50)
    vehicle_type = models.CharField(max_length=30)
    arrived_at = models.DateTimeField()
    sequence_no = models.IntegerField(null=True, blank=True)

    class Meta:
        unique_together = ('junction', 'vehicle_id')


class JunctionState(models.Model):
    junction = models.OneToOneField(Junction, on_delete=models.CASCADE, primary_key=True)
    mode = models.CharField(max_length=20, default='AUTOMATIC')
    phase = models.CharField(max_length=20, default='NORTH_SOUTH')
    stage = models.CharField(max_length=20, default='GREEN')
    desired_signals = models.JSONField(default=dict)
    actual_signals = models.JSONField(default=dict)
    emergency = models.JSONField(null=True, blank=True)
    manual = models.JSONField(null=True, blank=True)
    controller_status = models.CharField(max_length=20, default='ONLINE')
    stage_started_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)


class PendingCommand(models.Model):
    command_id = models.CharField(primary_key=True, max_length=50)
    junction = models.ForeignKey(Junction, on_delete=models.CASCADE)
    direction = models.CharField(max_length=10)
    requested_state = models.CharField(max_length=10)
    issued_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=20, default='PENDING')


class History(models.Model):
    junction = models.ForeignKey(Junction, on_delete=models.CASCADE)
    event_type = models.CharField(max_length=40)
    detail = models.JSONField(default=dict)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-id']
