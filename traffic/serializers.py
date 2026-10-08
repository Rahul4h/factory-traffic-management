from rest_framework import serializers


class SensorEventSerializer(serializers.Serializer):
    event_id = serializers.CharField(max_length=100)
    junction_id = serializers.CharField(max_length=10)
    direction = serializers.ChoiceField(choices=['NORTH', 'SOUTH', 'EAST', 'WEST'])
    event_type = serializers.ChoiceField(choices=['VEHICLE_ARRIVED', 'VEHICLE_CLEARED'])
    vehicle_id = serializers.CharField(max_length=50)
    vehicle_type = serializers.CharField(required=False, allow_blank=True)
    sequence_no = serializers.IntegerField(required=False, allow_null=True)
    timestamp = serializers.DateTimeField(required=False, allow_null=True)


class CommandSerializer(serializers.Serializer):
    command = serializers.ChoiceField(choices=['MANUAL_GREEN_REQUEST', 'RETURN_TO_AUTOMATIC'])
    direction = serializers.ChoiceField(
        choices=['NORTH', 'SOUTH', 'EAST', 'WEST'], required=False
    )


class ControllerEventSerializer(serializers.Serializer):
    command_id = serializers.CharField(required=False, allow_blank=True)
    junction_id = serializers.CharField()
    status = serializers.ChoiceField(choices=['ACK', 'OFFLINE', 'NACK'])
    actual_state = serializers.CharField(required=False, allow_blank=True)
