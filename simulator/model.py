"""Čistý zjednodušený model čtyřtaktního motoru, bez vláken a sítě."""

from dataclasses import dataclass
import math

# Výukové parametry mapy, nikoli kalibrace skutečného spalovacího motoru.
DEFAULT_THROTTLE = 0.35
# Počáteční držená dávka odpovídá původnímu výchozímu momentu (2,5 ms při 35 %).
# Pedál ji za běhu nepřepisuje: další dávky dodá pouze výstup ECU.
DEFAULT_INJECTION_MS = 0.875
DEFAULT_ADVANCE_DEG = 12.0
DEFAULT_LOAD_NM = 12.0
REFERENCE_INJECTION_MS = 3.0
REFERENCE_ADVANCE_DEG = 15.0
SPARK_TOLERANCE_DEG = 80.0
REFERENCE_TORQUE_NM = 100.0
REFERENCE_CYLINDERS = 4
FRICTION_BASE_NM = 5.0
FRICTION_PER_RPM = 0.005
MAP_CLOSED_KPA = 25.0
MAP_SPAN_KPA = 75.0


@dataclass(frozen=True)
class EngineConfig:
    cylinders: int = 4
    initial_rpm: float = 900.0
    inertia: float = 0.25
    max_rpm: float = 7500.0

    def __post_init__(self):
        if type(self.cylinders) is not int or not 1 <= self.cylinders <= 16:
            raise ValueError("cylinders must be 1..16")
        if not all(math.isfinite(x) for x in (self.initial_rpm, self.inertia, self.max_rpm)):
            raise ValueError("non-finite engine configuration")
        if self.inertia <= 0 or not 0 <= self.initial_rpm <= self.max_rpm <= 20000:
            raise ValueError("invalid engine configuration")


class EngineModel:
    def __init__(self, config=EngineConfig()):
        self.config = config
        self.rpm, self.angle = config.initial_rpm, 0.0
        self.throttle, self.injector_ms, self.ignition_deg = (
            DEFAULT_THROTTLE,
            DEFAULT_INJECTION_MS,
            DEFAULT_ADVANCE_DEG,
        )
        self.load_nm, self.target_rpm = DEFAULT_LOAD_NM, None
        self.open_injectors, self.charging = {}, {}
        self.last_injection_us, self.last_dwell_us = {}, {}

    def command(self, data):
        allowed = {"throttle", "injector_ms", "ignition_deg", "load_nm", "rpm", "idle"}
        if not isinstance(data, dict) or set(data) - allowed:
            raise ValueError("unknown actuator field")
        values = {k: (None if k == "rpm" and v is None else float(v)) for k, v in data.items()}
        if not all(v is None or math.isfinite(v) for v in values.values()):
            raise ValueError("non-finite actuator value")
        for key, value in values.items():
            if key == "rpm" and value is None:
                continue
            bounds = {
                "throttle": (0, 1),
                "idle": (0, 1),
                "injector_ms": (0, 100),
                "ignition_deg": (-180, 180),
                "load_nm": (0, 1000),
                "rpm": (0, self.config.max_rpm),
            }
            low, high = bounds[key]
            if not low <= value <= high:
                raise ValueError("actuator outside range: " + key)
        for key, value in values.items():
            if key == "rpm":
                self.target_rpm = value
                if value is not None:
                    self.rpm = value  # zkušební stolice s pevnými otáčkami
            elif key == "idle":
                self.throttle = value
            else:
                setattr(self, key, value)

    def event(self, data):
        signal, action = data.get("signal"), data.get("action")
        channel, timestamp = data.get("channel"), data.get("simulation_time_us")
        if type(channel) is not int or not 0 <= channel < self.config.cylinders:
            raise ValueError("invalid ECU channel")
        if type(timestamp) is not int or timestamp < 0:
            raise ValueError("invalid event time")
        if signal == "injector" and action in ("start", "end"):
            active, durations = self.open_injectors, self.last_injection_us
        elif signal == "ignition" and action in ("charge", "spark"):
            active, durations = self.charging, self.last_dwell_us
        else:
            raise ValueError("invalid ECU event")
        if action in ("start", "charge"):
            if channel in active:
                raise ValueError("duplicate pulse start")
            active[channel] = timestamp
        else:
            if channel not in active or timestamp < active[channel]:
                raise ValueError("unpaired or reversed ECU event")
            measured = data.get("duration_us", timestamp - active[channel])
            if type(measured) is not int or not 0 <= measured <= 1000000:
                raise ValueError("invalid measured pulse duration")
            durations[channel] = measured
            active.pop(channel)
            if signal == "injector":
                self.injector_ms = durations[channel] / 1000

    def step(self, dt):
        before = self.rpm
        fuel = max(0, min(1.5, self.injector_ms / REFERENCE_INJECTION_MS))
        spark = max(
            0.1,
            1 - abs(self.ignition_deg - REFERENCE_ADVANCE_DEG) / SPARK_TOLERANCE_DEG,
        )
        torque = REFERENCE_TORQUE_NM * self.config.cylinders / REFERENCE_CYLINDERS * fuel * spark
        acceleration = (
            torque - self.load_nm - FRICTION_BASE_NM - FRICTION_PER_RPM * self.rpm
        ) / self.config.inertia
        self.rpm = (
            self.target_rpm
            if self.target_rpm is not None
            else max(
                0,
                min(
                    self.config.max_rpm,
                    self.rpm + acceleration * 60 / (2 * math.pi) * dt,
                ),
            )
        )
        self.angle += (before + self.rpm) / 2 * 6 * dt

    def snapshot(self):
        # Jen orientační ukazatel směsi pro zachování původního zobrazení.
        # Tato reference vzduchu NEMĚNÍ dávku ani moment; ty určuje palivo z ECU.
        reference_air = REFERENCE_INJECTION_MS * self.throttle
        mixture = (
            reference_air / max(self.injector_ms, 0.1) if reference_air or self.injector_ms else 1
        )
        return {
            "rpm": self.rpm,
            "accelerator": self.throttle,
            "throttle": self.throttle,
            "tps": self.throttle,
            "map_kpa": MAP_CLOSED_KPA + MAP_SPAN_KPA * self.throttle,
            "iat_c": 25.0,
            "coolant_c": 85.0,
            "clt_c": 85.0,
            "crank_deg": self.angle % 720,
            "crank_angle_deg": self.angle % 360,
            "cycle_angle_deg": self.angle % 720,
            "lambda_value": max(0.6, min(2, mixture)),
            "cylinders": self.config.cylinders,
            "load_nm": self.load_nm,
            "injector_ms": self.injector_ms,
            "ignition_deg": self.ignition_deg,
            "fixed_rpm": self.target_rpm,
            "injector_active": sorted(self.open_injectors),
            "coil_charging": sorted(self.charging),
            "last_injection_us": dict(self.last_injection_us),
            "last_dwell_us": dict(self.last_dwell_us),
        }
