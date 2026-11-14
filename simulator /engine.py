"""Pracovní vlákno modelu; krok používá pouze virtuální čas."""
import heapq
import itertools
import queue
from threading import Thread, Event, RLock
from time import monotonic
from clock import SimulationClock
from model import EngineModel, EngineConfig
from signals import SignalGenerator

class Engine(Thread):
    def __init__(self, dt=.001, config=EngineConfig(), speed=1.0, signals=None, capacity=4096):
        super().__init__(name='engine', daemon=False)
        if not 0 < speed <= 1:
            raise ValueError('speed must be in (0,1]')
        if type(capacity) is not int or not 1 <= capacity <= 65536:
            raise ValueError('capacity must be in 1..65536')
        self.clock = SimulationClock(round(dt*1e6))
        self.dt, self.speed = self.clock.step_us/1e6, speed
        self.config, self.model = config, EngineModel(config)
        self.signals = signals or SignalGenerator()
        self.lock, self.stop_event, self.wake = RLock(), Event(), Event()
        self.paused = False
        self.invalidate_outputs = Event()
        self.generation = 0
        self.commands, self.events = queue.Queue(capacity), queue.Queue(capacity)
        self.pending, self.order = [], itertools.count()
        self.capacity = capacity
        self.diagnostics = {'dropped_events':0, 'rejected_commands':0, 'late_events':0,
                            'max_lateness_us':0, 'wall_lag_us':0, 'max_wall_lag_us':0}

    def command(self, data):
        self._enqueue(('command',dict(data)))

    def ecu_event(self, data):
        self._enqueue(('event',dict(data)))

    def invalidate(self):
        with self.lock:
            self.generation += 1
            self.invalidate_outputs.set()

    def _enqueue(self, item):
        with self.lock:
            try:
                self.commands.put_nowait((self.generation, *item))
            except queue.Full:
                raise BufferError('engine command queue full')

    def snapshot(self):
        with self.lock:
            return {**self.model.snapshot(), 'time_s':self.clock.time_us/1e6,
                    'simulation_time_us':self.clock.time_us, 'paused':self.paused,
                    'signal_levels': self.signals.levels(self.model.angle),
                    'diagnostics':dict(self.diagnostics)}

    def _apply(self, kind, data):
        try:
            if kind == 'command':
                self.model.command(data)
            else:
                self.model.event(data)
        except (ValueError, TypeError, OverflowError):
            self.diagnostics['rejected_commands'] += 1

    def step(self):
        with self.lock:
            if self.invalidate_outputs.is_set():
                self.pending.clear()
                self.model.open_injectors.clear()
                self.model.charging.clear()
                self.model.injector_ms = 0
                self.invalidate_outputs.clear()
            for _ in range(self.capacity):
                try:
                    generation, kind, data = self.commands.get_nowait()
                except queue.Empty:
                    break
                if generation != self.generation:
                    continue
                if kind == 'command':
                    self._apply(kind,data)
                else:
                    timestamp = data.get('simulation_time_us')
                    if type(timestamp) is not int or timestamp < 0 or len(self.pending) >= self.capacity:
                        self.diagnostics['rejected_commands'] += 1
                    else:
                        heapq.heappush(self.pending,(timestamp,next(self.order),data))
            if self.paused:
                return
            start_us = self.clock.time_us
            end_us = start_us+self.clock.step_us
            # Události rozdělí pevný makrokrok; palivo se projeví až po konci impulzu.
            cursor = start_us
            while self.pending and self.pending[0][0] <= end_us:
                timestamp, _, data = heapq.heappop(self.pending)
                applied = max(cursor,timestamp)
                self._advance_segment(cursor,applied)
                if timestamp < cursor:
                    self.diagnostics['late_events'] += 1
                    self.diagnostics['max_lateness_us'] = max(self.diagnostics['max_lateness_us'],cursor-timestamp)
                self._apply('event',data)
                cursor = applied
            self._advance_segment(cursor,end_us)
            self.clock.advance()

    def _advance_segment(self, start_us, end_us):
        if end_us <= start_us:
            return
        angle = self.model.angle
        self.model.step((end_us-start_us)/1e6)
        for edge in self.signals.edges(angle,self.model.angle,start_us,end_us):
            try:
                self.events.put_nowait(edge)
            except queue.Full:
                self.diagnostics['dropped_events'] += 1

    def drain_events(self, limit=512):
        result = []
        for _ in range(limit):
            try:
                result.append(self.events.get_nowait().data())
            except queue.Empty:
                break
        return result

    def pause(self):
        with self.lock:
            self.paused = True
        self.wake.set()

    def resume(self):
        with self.lock:
            self.paused = False
        self.wake.set()

    def reset(self):
        with self.lock:
            self.model = EngineModel(self.config)
            self.clock.reset()
            self.pending.clear()
            for q in (self.commands,self.events):
                while True:
                    try: q.get_nowait()
                    except queue.Empty: break
            for key in self.diagnostics: self.diagnostics[key] = 0
        self.wake.set()

    def run(self):
        deadline = monotonic()
        while not self.stop_event.is_set():
            self.step()
            with self.lock:
                paused = self.paused
            if paused:
                self.wake.wait(.1)
                self.wake.clear()
                deadline = monotonic()
                continue
            deadline += self.dt/self.speed
            lag = max(0,round((monotonic()-deadline)*1e6))
            with self.lock:
                self.diagnostics['wall_lag_us'] = lag
                self.diagnostics['max_wall_lag_us'] = max(lag,self.diagnostics['max_wall_lag_us'])
            # Pevný virtuální krok se při zpoždění nezvětšuje ani nepřeskakuje.
            self.wake.wait(max(0,deadline-monotonic()))
            self.wake.clear()

    def stop(self):
        self.stop_event.set()
        self.wake.set()
