"""Minimal four-stroke engine plant; educational SIL model, not combustion physics."""
from dataclasses import dataclass, asdict
from threading import Thread, Event, Lock
from time import monotonic, sleep

@dataclass
class EngineState:
    time_s: float = 0.0
    rpm: float = 900.0
    throttle: float = 0.15
    map_kpa: float = 40.0
    coolant_c: float = 85.0
    crank_deg: float = 0.0
    lambda_value: float = 1.0

@dataclass
class Actuators:
    injector_ms: float = 2.5
    ignition_deg: float = 12.0
    load_nm: float = 12.0

class Engine(Thread):
    def __init__(self, dt=0.01):
        super().__init__(daemon=True, name='engine')
        self.dt = dt
        self.state = EngineState()
        self.act = Actuators()
        self.lock = Lock()
        self.stop_event = Event()

    def command(self, data):
        with self.lock:
            for key in ('injector_ms', 'ignition_deg', 'load_nm'):
                if key in data:
                    setattr(self.act, key, float(data[key]))
            if 'throttle' in data:
                self.state.throttle = max(0.0, min(1.0, float(data['throttle'])))

    def snapshot(self):
        with self.lock:
            return asdict(self.state)

    def step(self):
        with self.lock:
            s, a, dt = self.state, self.act, self.dt
            s.map_kpa = 25.0 + 75.0 * s.throttle
            # Toy torque map, intentionally not calibrated to a real engine.
            fuel_factor = max(0.0, min(1.5, a.injector_ms / 3.0))
            spark_factor = max(0.1, 1.0 - abs(a.ignition_deg - 15.0) / 80.0)
            torque = 100.0 * s.throttle * fuel_factor * spark_factor
            friction = 5.0 + 0.005 * s.rpm
            inertia = 0.25  # kg*m^2
            acceleration = (torque - a.load_nm - friction) / inertia
            s.rpm = max(0.0, min(7500.0, s.rpm + acceleration * 60.0 / (2.0 * 3.141592653589793) * dt))
            s.crank_deg = (s.crank_deg + s.rpm * 6.0 * dt) % 720.0
            s.lambda_value = max(0.6, min(2.0, 3.0 / max(a.injector_ms, 0.1)))
            s.time_s += dt

    def run(self):
        deadline = monotonic()
        while not self.stop_event.is_set():
            self.step()
            deadline += self.dt
            delay = deadline - monotonic()
            if delay > 0:
                self.stop_event.wait(delay)
            else:
                deadline = monotonic()

    def stop(self):
        self.stop_event.set()
