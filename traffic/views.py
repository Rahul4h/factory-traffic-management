from rest_framework.decorators import api_view
from rest_framework.response import Response
from django.shortcuts import render
from django.utils import timezone

from .models import Junction, ProcessedEvent, QueueEntry, History, PendingCommand
from .serializers import SensorEventSerializer, CommandSerializer, ControllerEventSerializer
from .registry import get_engine, ensure_junction, persist_state, log_history


def dashboard(request):
    return render(request, 'dashboard.html')


# ============================================================
# JUNCTIONS
# ============================================================

@api_view(['GET'])
def list_junctions(request):
    return Response([{'id': j.id, 'config': j.config} for j in Junction.objects.all()])


@api_view(['GET'])
def get_junction(request, jid):
    try:
        j = Junction.objects.get(pk=jid)
    except Junction.DoesNotExist:
        return Response({'error': 'Unknown junction'}, status=404)
    return Response({'id': j.id, 'config': j.config})


@api_view(['POST'])
def create_junction(request):
    jid = request.data.get('id')
    if not jid:
        return Response({'error': 'id required'}, status=400)
    Junction.objects.get_or_create(
        pk=jid,
        defaults={'config': request.data.get('config') or {
            'greenMs': 30000, 'yellowMs': 5000, 'allRedMs': 2000}}
    )
    ensure_junction(jid)
    return Response({'id': jid}, status=201)


# ============================================================
# JUNCTION STATUS
# ============================================================

@api_view(['GET'])
def junction_status(request, jid):
    engine = get_engine(jid)
    if not engine:
        return Response({'error': 'Unknown junction'}, status=404)
    return Response(engine.snapshot())


# ============================================================
# SENSOR EVENTS (idempotent by event_id)
# ============================================================

@api_view(['POST'])
def sensor_event(request):
    s = SensorEventSerializer(data=request.data)
    if not s.is_valid():
        return Response(s.errors, status=400)
    d = s.validated_data

    # Junction must exist
    if not Junction.objects.filter(pk=d['junction_id']).exists():
        return Response({'error': 'Unknown junction'}, status=404)
    j = Junction.objects.get(pk=d['junction_id'])

    # Idempotency: same event_id processed once only
    if ProcessedEvent.objects.filter(pk=d['event_id']).exists():
        log_history(j, 'DUPLICATE_EVENT', {'event_id': d['event_id']})
        return Response({'duplicate': True}, status=200)

    engine = get_engine(d['junction_id'])
    if not engine:
        return Response({'error': 'Engine unavailable'}, status=500)

    # ---------------- VEHICLE ARRIVED ----------------
    if d['event_type'] == 'VEHICLE_ARRIVED':
        vt = d.get('vehicle_type') or 'EMPLOYEE_VEHICLE'
        added = engine.add_vehicle(d['direction'], d['vehicle_id'], vt, d.get('sequence_no'))
        if added:
            QueueEntry.objects.update_or_create(
                junction_id=d['junction_id'],
                vehicle_id=d['vehicle_id'],
                defaults={
                    'direction': d['direction'],
                    'vehicle_type': vt,
                    'arrived_at': timezone.now(),
                    'sequence_no': d.get('sequence_no'),
                }
            )
            if vt == 'EMERGENCY':
                engine.register_emergency(d['direction'], d['vehicle_id'])
                log_history(j, 'EMERGENCY_DETECTED', {
                    'direction': d['direction'],
                    'vehicle': d['vehicle_id']
                })
            else:
                log_history(j, 'VEHICLE_DETECTED', {
                    'direction': d['direction'],
                    'vehicle': d['vehicle_id'],
                    'vehicle_type': vt,
                })

    # ---------------- VEHICLE CLEARED ----------------
    elif d['event_type'] == 'VEHICLE_CLEARED':
        engine.clear_vehicle(d['direction'], d['vehicle_id'])
        QueueEntry.objects.filter(
            junction_id=d['junction_id'],
            vehicle_id=d['vehicle_id']
        ).delete()

        if engine.emergency and engine.emergency.get('vehicleId') == d['vehicle_id']:
            engine.clear_emergency()
            log_history(j, 'EMERGENCY_CLEARED', {'vehicle': d['vehicle_id']})
        else:
            log_history(j, 'VEHICLE_CLEARED', {'vehicle': d['vehicle_id']})

    # Mark processed
    ProcessedEvent.objects.create(event_id=d['event_id'])
    persist_state(engine)
    return Response({'accepted': True}, status=202)


# ============================================================
# MANUAL / CONTROL COMMANDS
# ============================================================

@api_view(['POST'])
def junction_command(request, jid):
    engine = get_engine(jid)
    if not engine:
        return Response({'error': 'Unknown junction'}, status=404)

    s = CommandSerializer(data=request.data)
    if not s.is_valid():
        return Response(s.errors, status=400)

    cmd = s.validated_data['command']
    j = Junction.objects.get(pk=jid)

    if cmd == 'MANUAL_GREEN_REQUEST':
        direction = s.validated_data.get('direction')
        if not direction:
            return Response({'error': 'direction required for MANUAL_GREEN_REQUEST'}, status=400)
        engine.manual_request(direction, 60_000)
        engine.mode = 'MANUAL'
        log_history(j, 'MANUAL_OVERRIDE', {'direction': direction})

    elif cmd == 'RETURN_TO_AUTOMATIC':
        engine.return_to_automatic()
        log_history(j, 'RETURN_TO_AUTOMATIC', {})

    persist_state(engine)
    return Response({
        'ok': True,
        'mode': engine.mode,
        'phase': engine.phase,
        'stage': engine.stage,
    })


# ============================================================
# CONTROLLER EVENTS (ACK / OFFLINE / NACK)
# ============================================================

@api_view(['POST'])
def controller_event(request):
    s = ControllerEventSerializer(data=request.data)
    if not s.is_valid():
        return Response(s.errors, status=400)

    d = s.validated_data
    engine = get_engine(d['junction_id'])
    if not engine:
        return Response({'error': 'Unknown junction'}, status=404)

    j = Junction.objects.get(pk=d['junction_id'])

    # ---------------- OFFLINE ----------------
    if d['status'] == 'OFFLINE':
        engine.controller_status = 'OFFLINE'
        engine.mode = 'DEGRADED'
        log_history(j, 'CONTROLLER_OFFLINE', {
            'command_id': d.get('command_id'),
        })

    # ---------------- ACK ----------------
    elif d['status'] == 'ACK':
        engine.controller_status = 'ONLINE'

        # If ACK restores from DEGRADED, bring mode back
        if engine.mode == 'DEGRADED':
            if engine.emergency:
                engine.mode = 'EMERGENCY'
            elif engine.manual:
                engine.mode = 'MANUAL'
            else:
                engine.mode = 'AUTOMATIC'

        # Update actual_signals for the specific direction if provided
        direction = d.get('direction')
        actual_state = d.get('actual_state')

        if direction and actual_state:
            if direction in engine.actual_signals:
                engine.actual_signals[direction] = actual_state
        elif actual_state:
            # No direction given — reconcile all signals to desired
            # (used by the simple dashboard ACK button)
            desired = engine.desired_signals()
            engine.actual_signals = dict(desired)

        log_history(j, 'CONTROLLER_ACK', {
            'command_id': d.get('command_id'),
            'direction': direction,
            'actual_state': actual_state,
        })

        # Mark pending command as acked
        cid = d.get('command_id')
        if cid:
            PendingCommand.objects.filter(command_id=cid).update(status='ACKED')

    # ---------------- NACK ----------------
    elif d['status'] == 'NACK':
        log_history(j, 'CONTROLLER_NACK', {
            'command_id': d.get('command_id'),
            'actual_state': d.get('actual_state'),
        })
        # Safety: controller refused a command → don't assume it happened.
        # Keep mode as-is but log for operator attention.
        cid = d.get('command_id')
        if cid:
            PendingCommand.objects.filter(command_id=cid).update(status='NACKED')

    persist_state(engine)
    return Response({
        'ok': True,
        'controller_status': engine.controller_status,
        'mode': engine.mode,
    })


# ============================================================
# HISTORY
# ============================================================

@api_view(['GET'])
def junction_history(request, jid):
    if not Junction.objects.filter(pk=jid).exists():
        return Response({'error': 'Unknown junction'}, status=404)
    rows = History.objects.filter(junction_id=jid)[:200]
    return Response([{
        'id': r.id,
        'event_type': r.event_type,
        'detail': r.detail,
        'timestamp': r.timestamp.isoformat(),
    } for r in rows])