"""Pure traffic-domain logic. No Django, no HTTP, no DB."""
import time

DIRECTIONS = ['NORTH', 'SOUTH', 'EAST', 'WEST']

PHASES = {
    'NORTH_SOUTH': {'green': ['NORTH', 'SOUTH'], 'red': ['EAST', 'WEST']},
    'EAST_WEST':   {'green': ['EAST', 'WEST'],   'red': ['NORTH', 'SOUTH']},
}

VEHICLE_PRIORITY = {
    'EMERGENCY': 100,
    'TRUCK': 40,
    'FORKLIFT': 20,
    'EMPLOYEE_VEHICLE': 5,
}


class JunctionEngine:
    def __init__(self, junction_id, config=None):
        self.junction_id = junction_id
        cfg = config or {}
        self.green_ms = cfg.get('greenMs', 30_000)
        self.yellow_ms = cfg.get('yellowMs', 5_000)
        self.all_red_ms = cfg.get('allRedMs', 2_000)

        self.mode = 'AUTOMATIC'
        self.phase = 'NORTH_SOUTH'
        self.stage = 'GREEN'
        self.stage_started = time.time() * 1000

        self.queues = {d: [] for d in DIRECTIONS}
        self.emergency = None
        self.manual = None
        self.controller_status = 'ONLINE'
        self.pending_command = None
        # actual_signals = controller-confirmed state
        # Initially we assume actual matches desired (cold start)
        self.actual_signals = self._signals_for('GREEN', 'NORTH_SOUTH')

    # ------------------------------------------------------------
    # Signal computation
    # ------------------------------------------------------------
    def _signals_for(self, stage, phase):
        green = PHASES[phase]['green']
        red = PHASES[phase]['red']
        out = {}
        if stage == 'GREEN':
            for d in green: out[d] = 'GREEN'
            for d in red:   out[d] = 'RED'
        elif stage == 'YELLOW':
            for d in green: out[d] = 'YELLOW'
            for d in red:   out[d] = 'RED'
        else:  # ALL_RED
            for d in DIRECTIONS: out[d] = 'RED'
        return out

    def desired_signals(self):
        return self._signals_for(self.stage, self.phase)

    # ------------------------------------------------------------
    # Queue operations
    # ------------------------------------------------------------
    def add_vehicle(self, direction, vehicle_id, vehicle_type, seq=None):
        if direction not in DIRECTIONS:
            return False
        # Duplicate vehicle in same direction → ignore
        if any(v['vehicleId'] == vehicle_id for v in self.queues[direction]):
            return False
        self.queues[direction].append({
            'vehicleId': vehicle_id,
            'vehicleType': vehicle_type if vehicle_type in VEHICLE_PRIORITY else 'EMPLOYEE_VEHICLE',
            'arrivedAt': time.time() * 1000,
            'sequenceNo': seq,
        })
        return True

    def clear_vehicle(self, direction, vehicle_id):
        if direction not in DIRECTIONS:
            return False
        before = len(self.queues[direction])
        self.queues[direction] = [v for v in self.queues[direction] if v['vehicleId'] != vehicle_id]
        return before != len(self.queues[direction])

    # ------------------------------------------------------------
    # Emergency
    # ------------------------------------------------------------
    def register_emergency(self, direction, vehicle_id):
        """First emergency wins until cleared."""
        if self.emergency is None:
            self.emergency = {
                'direction': direction,
                'vehicleId': vehicle_id,
                'since': time.time() * 1000,
            }
            self.mode = 'EMERGENCY'
            return True
        return False

    def clear_emergency(self):
        if self.emergency:
            self.emergency = None
            now = time.time() * 1000
            if self.manual and self.manual['until'] > now:
                self.mode = 'MANUAL'
            else:
                self.mode = 'AUTOMATIC'

    # ------------------------------------------------------------
    # Manual
    # ------------------------------------------------------------
    def manual_request(self, direction, duration_ms=60_000):
        self.manual = {
            'direction': direction,
            'until': time.time() * 1000 + duration_ms,
        }

    def return_to_automatic(self):
        self.manual = None
        self.mode = 'EMERGENCY' if self.emergency else 'AUTOMATIC'

    # ------------------------------------------------------------
    # Scheduling
    # ------------------------------------------------------------
    def _phase_score(self, phase):
        """Higher score → more urgent phase."""
        score = 0.0
        now = time.time() * 1000
        for d in PHASES[phase]['green']:
            q = self.queues[d]
            if not q:
                continue
            priority_sum = sum(VEHICLE_PRIORITY[v['vehicleType']] for v in q)
            max_wait_s = max((now - v['arrivedAt']) / 1000 for v in q)
            score += len(q) * 10 + priority_sum + max_wait_s * 0.5
        return score

    def _choose_target_phase(self):
        """Decide which phase should be GREEN next."""
        # 1. Emergency overrides everything
        if self.emergency:
            if self.emergency['direction'] in PHASES['NORTH_SOUTH']['green']:
                return 'NORTH_SOUTH'
            return 'EAST_WEST'

        # 2. Manual override (until expiry)
        now = time.time() * 1000
        if self.manual and self.manual['until'] > now:
            if self.manual['direction'] in PHASES['NORTH_SOUTH']['green']:
                return 'NORTH_SOUTH'
            return 'EAST_WEST'

        # 3. Automatic scoring
        a = self._phase_score('NORTH_SOUTH')
        b = self._phase_score('EAST_WEST')

        cur_score = a if self.phase == 'NORTH_SOUTH' else b
        other_score = b if self.phase == 'NORTH_SOUTH' else a
        other_phase = 'EAST_WEST' if self.phase == 'NORTH_SOUTH' else 'NORTH_SOUTH'

        # --- FIX #1: Idle fairness ---
        # Both phases empty → alternate so EAST_WEST also gets GREEN.
        if cur_score == 0 and other_score == 0:
            return other_phase

        # Current phase empty, other has traffic → switch
        if cur_score == 0 and other_score > 0:
            return other_phase

        # Hysteresis: only switch if other is 20% busier (prevents flapping)
        if other_score > cur_score * 1.2:
            return other_phase

        return self.phase

    # ------------------------------------------------------------
    # Main tick — advances state machine
    # ------------------------------------------------------------
    def tick(self):
        """Advance the state machine by one step based on elapsed time.
        Returns True if a state transition occurred.
        """
        now = time.time() * 1000
        elapsed = now - self.stage_started
        changed = False

        if self.stage == 'GREEN':
            # Emergency caps current green to 5s max
            dur = min(5_000, self.green_ms) if self.emergency else self.green_ms
            if elapsed >= dur:
                self.stage = 'YELLOW'
                self.stage_started = now
                changed = True

        elif self.stage == 'YELLOW':
            if elapsed >= self.yellow_ms:
                self.stage = 'ALL_RED'
                self.stage_started = now
                changed = True

        elif self.stage == 'ALL_RED':
            if elapsed >= self.all_red_ms:
                self.phase = self._choose_target_phase()
                self.stage = 'GREEN'
                self.stage_started = now
                changed = True

        # Manual override auto-expiry
        if self.manual and self.manual['until'] <= now:
            self.manual = None
            if not self.emergency:
                self.mode = 'AUTOMATIC'

        # --- FIX #2: keep actual_signals aligned with desired ---
        # In a real system, this would be updated only by controller ACKs.
        # For this simulator, we auto-reconcile on transition to avoid
        # permanent desired-vs-actual drift. Overridden by explicit ACKs.
        if changed:
            desired = self.desired_signals()
            for d in DIRECTIONS:
                self.actual_signals[d] = desired[d]

        return changed

    # ------------------------------------------------------------
    # Snapshot for API
    # ------------------------------------------------------------
    def snapshot(self):
        return {
            'junction_id': self.junction_id,
            'mode': self.mode,
            'phase': self.phase,
            'stage': self.stage,
            'controller_status': self.controller_status,
            'desired_signals': self.desired_signals(),
            'actual_signals': self.actual_signals,
            'queues': {d: len(self.queues[d]) for d in DIRECTIONS},
            'emergency': self.emergency,
            'manual': self.manual,
            'pending_command': self.pending_command,
        }