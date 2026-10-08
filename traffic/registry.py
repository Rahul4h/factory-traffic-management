import threading, time
from django.utils import timezone
from .engine import JunctionEngine, DIRECTIONS
from .models import Junction, QueueEntry, JunctionState, History

_engines = {}
_lock = threading.RLock()


def log_history(junction, event_type, detail=None):
    History.objects.create(junction=junction, event_type=event_type, detail=detail or {})


def get_engine(junction_id):
    with _lock:
        if junction_id in _engines:
            return _engines[junction_id]
        try:
            j = Junction.objects.get(pk=junction_id)
        except Junction.DoesNotExist:
            return None
        engine = JunctionEngine(junction_id, j.config)
        for q in QueueEntry.objects.filter(junction_id=junction_id):
            engine.queues[q.direction].append({
                'vehicleId': q.vehicle_id,
                'vehicleType': q.vehicle_type,
                'arrivedAt': q.arrived_at.timestamp() * 1000,
                'sequenceNo': q.sequence_no,
            })
        try:
            st = JunctionState.objects.get(pk=junction_id)
            engine.mode = st.mode
            engine.phase = st.phase
            engine.stage = 'ALL_RED'
            engine.stage_started = time.time() * 1000
            engine.emergency = st.emergency
            engine.manual = st.manual
            engine.controller_status = st.controller_status
        except JunctionState.DoesNotExist:
            pass
        _engines[junction_id] = engine
        return engine


def persist_state(engine):
    with _lock:
        j = Junction.objects.get(pk=engine.junction_id)
        JunctionState.objects.update_or_create(
            junction=j,
            defaults={
                'mode': engine.mode,
                'phase': engine.phase,
                'stage': engine.stage,
                'desired_signals': engine.desired_signals(),
                'actual_signals': engine.actual_signals,
                'emergency': engine.emergency,
                'manual': engine.manual,
                'controller_status': engine.controller_status,
                'stage_started_at': timezone.now(),
            }
        )


def ensure_junction(junction_id):
    Junction.objects.get_or_create(
        pk=junction_id,
        defaults={'config': {'greenMs': 30000, 'yellowMs': 5000, 'allRedMs': 2000}}
    )
    return get_engine(junction_id)
