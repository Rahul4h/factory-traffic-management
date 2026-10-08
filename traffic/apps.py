from django.apps import AppConfig
import os
import sys


class TrafficConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'traffic'

    def ready(self):
        """
        Start the background scheduler thread that drives the traffic
        state machine (tick every 500ms).

        Rules:
        - Skip for management commands that don't need it (migrate, makemigrations, etc.)
        - For runserver with autoreload, only the main process starts the thread.
        - For shell/gunicorn/other commands, start in-process.
        """
        # Don't start scheduler during these commands
        skip_commands = {'migrate', 'makemigrations', 'collectstatic', 'test', 'createsuperuser'}
        if any(cmd in sys.argv for cmd in skip_commands):
            return

        # For runserver: only start in the main process (avoid double start with autoreload)
        if 'runserver' in sys.argv:
            # Django autoreload sets RUN_MAIN='true' in the child process
            if os.environ.get('RUN_MAIN') == 'true':
                self._start_scheduler()
            return

        # For shell, gunicorn, or any other command: start here
        self._start_scheduler()

    def _start_scheduler(self):
        try:
            from . import scheduler
            scheduler.start()
            print('[traffic] scheduler started')
        except Exception as e:
            print('[traffic] scheduler start failed:', e)