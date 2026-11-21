"""Pracovní vlákno modelu; krok používá pouze virtuální čas."""

import heapq
import itertools
import queue
from threading import Thread, Event, RLock
from time import monotonic
from clock import SimulationClock
from model import EngineModel, EngineConfig
from signals import SignalGenerator
from ecu_status import STATES, fault_names


class Engine(Thread):
    def __init__(
        self,
        dt=0.001,
        config=EngineConfig(),
        speed=1.0,
        signals=None,
        capacity=4096,
        collect_events=False,
        max_wall_lag=0.25,
        max_future_event_us=2000000,
        vehicle=False,
    ):
        super().__init__(name="engine", daemon=False)
        if not 0 < speed <= 1:
            raise ValueError("speed must be in (0,1]")
        if type(capacity) is not int or not 1 <= capacity <= 65536:
            raise ValueError("capacity must be in 1..65536")
        self.clock = SimulationClock(round(dt * 1e6))
        self.dt, self.speed = self.clock.step_us / 1e6, speed
        if not 0 < max_wall_lag <= 10:
            raise ValueError("max_wall_lag must be in (0,10] seconds")
        self.max_wall_lag = max_wall_lag
        if type(max_future_event_us) is not int or max_future_event_us <= 0:
            raise ValueError("max_future_event_us must be a positive integer")
        self.max_future_event_us = max_future_event_us
        self.local_ecu = None
        self.collect_events = collect_events
        self.config, self.model = config, EngineModel(config)
        from vehicle import VehicleModel

        self.vehicle = VehicleModel() if vehicle else None
        self.driving = None
        self.signals = signals or SignalGenerator()
        self.lock, self.stop_event, self.wake = RLock(), Event(), Event()
        self.paused = False
        self.invalidate_outputs = Event()
        self.generation = 0
        self.commands, self.events = queue.Queue(capacity), queue.Queue(capacity)
        self.pending, self.order = [], itertools.count()
        self.capacity = capacity
        self.diagnostics = {
            "dropped_events": 0,
            "rejected_commands": 0,
            "late_events": 0,
            "max_lateness_us": 0,
            "wall_lag_us": 0,
            "max_wall_lag_us": 0,
            "pacing_resets": 0,
            "future_events_rejected": 0,
        }

    def command(self, data):
        self._enqueue(("command", dict(data)))

    def set_vehicle_enabled(self, enabled):
        from vehicle import VehicleModel

        with self.lock:
            if enabled and self.vehicle is None:
                self.vehicle = VehicleModel(start_us=self.clock.time_us)
                # CAN i podvozek navazují na stejný virtuální čas motoru.
            elif not enabled:
                self.vehicle = None
                self.driving = None
                self.model.vehicle_physics = False
            self.model.drivetrain_load_nm = 0.0
            self.model.torque_factor = 1.0

    def enable_driving(self):
        from racetrack import DrivingSession
        from vehicle import VehicleModel

        with self.lock:
            self.vehicle = VehicleModel(start_us=self.clock.time_us)
            self.driving = DrivingSession(self.clock.time_us)
            self.vehicle.heading = self.driving.heading
            self.vehicle.command({"selector": "D", "brake": 1.0})
            self.model.command({"throttle": 0.0})
            self.model.drivetrain_load_nm = 0.0
            self.model.torque_factor = 1.0
            self.paused = True
        self.wake.set()

    def drive_input(self, throttle, brake, steer_deg, source="keyboard"):
        import math

        values = (throttle, brake, steer_deg)
        if (
            not all(type(x) in (int, float) and math.isfinite(x) for x in values)
            or not 0 <= throttle <= 1
            or not 0 <= brake <= 1
            or not -30 <= steer_deg <= 30
            or source not in ("keyboard", "joypad", "demo")
        ):
            raise ValueError("Neplatné ovládání jízdy")
        with self.lock:
            if self.driving is None or self.vehicle is None:
                raise ValueError("Režim jízdy není zapnutý")
            self.model.command({"throttle": throttle})
            self.vehicle.command({"brake": brake, "steer_deg": steer_deg})
            self.driving.last_input_us = self.clock.time_us
            self.driving.source = source

    def pause_driving(self, reason="Jízda pozastavena"):
        with self.lock:
            if self.driving is not None:
                self.driving.armed = False
                self.driving.input_fault = reason
                self.model.command({"throttle": 0.0})
                self.vehicle.command({"brake": 1.0, "steer_deg": 0.0})
                self.paused = True
        self.wake.set()

    def resume_driving(self):
        with self.lock:
            if self.driving is None:
                raise ValueError("Režim jízdy není zapnutý")
            self.driving.armed = True
            self.driving.input_fault = ""
            self.driving.last_input_us = self.clock.time_us
            self.paused = False
        self.wake.set()

    def vehicle_command(self, data):
        if self.vehicle is None:
            raise ValueError("Režim auta není zapnutý")
        self._enqueue(("vehicle", dict(data)))

    def ecu_event(self, data):
        self._enqueue(("event", dict(data)))

    def invalidate(self):
        with self.lock:
            self.generation += 1
            self.invalidate_outputs.set()

    def _enqueue(self, item):
        with self.lock:
            try:
                self.commands.put_nowait((self.generation, *item))
            except queue.Full:
                raise BufferError("engine command queue full")

    def snapshot(self):
        with self.lock:
            return {
                **self.model.snapshot(),
                **(
                    {
                        "vehicle": self.vehicle.snapshot(),
                        "coolant_c": self.vehicle.coolant,
                        "clt_c": self.vehicle.coolant,
                    }
                    if self.vehicle is not None
                    else {}
                ),
                **({"driving": self.driving.snapshot()} if self.driving is not None else {}),
                "time_s": self.clock.time_us / 1e6,
                "simulation_time_us": self.clock.time_us,
                "paused": self.paused,
                "signal_levels": self.signals.levels(self.model.angle),
                "diagnostics": dict(self.diagnostics),
            }

    def _apply(self, kind, data):
        try:
            if kind == "command":
                self.model.command(data)
            elif kind == "vehicle" and self.vehicle is not None:
                self.vehicle.command(data)
            else:
                self.model.event(data)
        except (ValueError, TypeError, OverflowError):
            self.diagnostics["rejected_commands"] += 1

    def step(self):
        with self.lock:
            if self.invalidate_outputs.is_set():
                self.pending.clear()
                self.model.open_injectors.clear()
                self.model.charging.clear()
                if self.local_ecu is not None:
                    self.local_ecu.reset(self.clock.time_us, self.model.throttle)
                self.invalidate_outputs.clear()
            for _ in range(self.capacity):
                try:
                    generation, kind, data = self.commands.get_nowait()
                except queue.Empty:
                    break
                if generation != self.generation:
                    continue
                if kind in ("command", "vehicle"):
                    self._apply(kind, data)
                else:
                    timestamp = data.get("simulation_time_us")
                    if (
                        type(timestamp) is int
                        and timestamp > self.clock.time_us + self.max_future_event_us
                    ):
                        self.diagnostics["future_events_rejected"] += 1
                        continue
                    if (
                        type(timestamp) is not int
                        or timestamp < 0
                        or len(self.pending) >= self.capacity
                    ):
                        self.diagnostics["rejected_commands"] += 1
                    else:
                        heapq.heappush(self.pending, (timestamp, next(self.order), data))
            if self.driving is not None:
                if self.driving.armed and self.clock.time_us - self.driving.last_input_us > 500_000:
                    self.pause_driving("Vstup se neobnovil do 0,5 s simulačního času")
                if not self.driving.armed:
                    self.paused = True
            if self.paused:
                return
            automotive = self.vehicle is not None and self.local_ecu is not None
            self.model.vehicle_physics = automotive
            if self.local_ecu is not None:
                if automotive:
                    inputs = self.vehicle.ecu_inputs(self.model)
                    self.local_ecu.set_vehicle_inputs(inputs, self.clock.time_us)
                    self.model.battery_v = inputs["battery_v"]
                    self.model.fuel_rail_kpa = inputs["rail_kpa"]
                else:
                    self.local_ecu.set_vehicle_inputs(None, self.clock.time_us)
            start_us = self.clock.time_us
            end_us = start_us + self.clock.step_us
            # Události rozdělí pevný makrokrok; palivo se projeví až po konci impulzu.
            cursor = start_us
            while self.pending and self.pending[0][0] <= end_us:
                timestamp, _, data = heapq.heappop(self.pending)
                applied = max(cursor, timestamp)
                self._advance_segment(cursor, applied)
                if timestamp < cursor:
                    self.diagnostics["late_events"] += 1
                    self.diagnostics["max_lateness_us"] = max(
                        self.diagnostics["max_lateness_us"], cursor - timestamp
                    )
                self._apply("event", data)
                cursor = applied
            self._advance_segment(cursor, end_us)
            # Auto integrujeme JEDNOU po dokončení motorového makrokroku.
            # Predikce CKP v _advance_segment nesmí posunout podvozek podruhé.
            if self.vehicle is not None:
                if self.driving is not None:
                    self.driving.before_step(self.vehicle)
                self.vehicle.motor_sensors = self.model.snapshot()
                self.vehicle.step(
                    self.dt,
                    self.model.rpm,
                    self.model.combustion_torque(),
                    self.model.throttle,
                    self.model.injector_ms * 1000,
                    self.config.cylinders,
                )
                if self.driving is not None:
                    self.driving.step(self.vehicle, self.dt, end_us)
                self.model.drivetrain_load_nm = self.vehicle.engine_load_nm
                # Požadavek ESP už provádí automobilní ECU přes vzduch: neškrtit podruhé.
                self.model.torque_factor = 1.0 if automotive else self.vehicle.torque_factor
                if automotive:
                    throttle, pulse, mode, faults = self.local_ecu.vehicle_output()
                    self.model.throttle_target = throttle
                    self.vehicle.ecu_status = {
                        "mode": mode,
                        "state_name": STATES.get(mode, "NEZNÁMÝ"),
                        "fault_names": fault_names(faults),
                        "faults": faults,
                        "throttle_target": throttle,
                        "injection_us": pulse,
                    }
            self.clock.advance()

    def _advance_segment(self, start_us, end_us):
        if end_us <= start_us:
            return
        angle, rpm, air = self.model.angle, self.model.rpm, self.model.air_throttle
        self.model.step((end_us - start_us) / 1e6)
        if not self.collect_events and self.local_ecu is None:
            return
        edges = self.signals.edges(angle, self.model.angle, start_us, end_us)
        if self.local_ecu is not None:
            # Predikce úhlu v makrokroku určí časy snímačů. Potom krok integrujeme
            # znovu po skutečných výstupech ECU: dávka se projeví až po konci pulzu.
            self.model.angle, self.model.rpm, self.model.air_throttle = angle, rpm, air
            cursor = start_us
            for event in self.local_ecu.advance(end_us, edges, self.model.throttle):
                timestamp = event["simulation_time_us"]
                self.model.step((timestamp - cursor) / 1e6)
                self._apply("event", event)
                if "ignition_deg" in event:
                    self._apply("command", {"ignition_deg": event["ignition_deg"]})
                cursor = timestamp
            self.model.step((end_us - cursor) / 1e6)
        if self.collect_events:
            for edge in edges:
                try:
                    self.events.put_nowait(edge)
                except queue.Full:
                    self.diagnostics["dropped_events"] += 1

    def drain_events(self, limit=512):
        result = []
        for _ in range(limit):
            try:
                result.append(self.events.get_nowait().data())
            except queue.Empty:
                break
        return result

    def set_speed(self, speed):
        if not 0 < speed <= 1:
            raise ValueError("speed must be in (0,1]")
        with self.lock:
            self.speed = speed
        self.wake.set()

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
            if self.vehicle is not None:
                from vehicle import VehicleModel

                self.vehicle = VehicleModel(self.vehicle.config)
            if self.driving is not None:
                from racetrack import DrivingSession

                self.driving = DrivingSession()
                self.vehicle.heading = self.driving.heading
                self.vehicle.command({"selector": "D", "brake": 1.0})
                self.model.command({"throttle": 0.0})
                self.paused = True
            self.clock.reset()
            if self.local_ecu is not None:
                self.local_ecu.reset(0, self.model.throttle)
            self.pending.clear()
            for q in (self.commands, self.events):
                while True:
                    try:
                        q.get_nowait()
                    except queue.Empty:
                        break
            for key in self.diagnostics:
                self.diagnostics[key] = 0
        self.wake.set()

    def bound_deadline(self, deadline, now):
        """Po suspendu zahodíme wall-time dluh; virtuální kroky nikdy nepřeskakujeme."""
        if now - deadline > self.max_wall_lag:
            with self.lock:
                self.diagnostics["pacing_resets"] += 1
            return now
        return deadline

    def run(self):
        deadline = monotonic()
        previous_speed = self.speed
        while not self.stop_event.is_set():
            with self.lock:
                speed = self.speed
            if speed != previous_speed:
                deadline = monotonic()
                previous_speed = speed
            self.step()
            with self.lock:
                paused = self.paused
            if paused:
                self.wake.wait(0.1)
                self.wake.clear()
                deadline = monotonic()
                continue
            deadline += self.dt / speed
            lag = max(0, round((monotonic() - deadline) * 1e6))
            with self.lock:
                self.diagnostics["wall_lag_us"] = lag
                self.diagnostics["max_wall_lag_us"] = max(lag, self.diagnostics["max_wall_lag_us"])
            deadline = self.bound_deadline(deadline, monotonic())
            # Při běžném jitteru doháníme; velký wall dluh se mění na zpomalení simulace.
            self.wake.wait(max(0, deadline - monotonic()))
            self.wake.clear()

    def stop(self):
        self.stop_event.set()
        self.wake.set()
