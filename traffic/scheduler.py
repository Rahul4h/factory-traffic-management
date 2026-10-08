import threading, time
from django.db import close_old_connections
from .registry import _engines, persist_state

_thread = None


def _log_by_id(junction_id, event_type, detail):
    from .models import Junction, History
    try:
        j = Junction.objects.get(pk=junction_id)
        History.objects.create(junction=j, event_type=event_type, detail=detail or {})
    except Junction.DoesNotExist:
        pass


def _loop():
    while True:
        try:
            close_old_connections()
            for jid, engine in list(_engines.items()):
                if engine.tick():
                    _log_by_id(jid, 'SIGNAL_TRANSITION', {
                        'phase': engine.phase,
                        'stage': engine.stage,
                        'desired': engine.desired_signals(),
                    })
                    persist_state(engine)
        except Exception as e:
            print('scheduler error:', e)
        time.sleep(0.5)


def start():
    global _thread
    if _thread is None:
        _thread = threading.Thread(target=_loop, daemon=True)
        _thread.start()
