"""Čistý zjednodušený model čtyřtaktního motoru, bez vláken a sítě."""
from dataclasses import dataclass
import math

@dataclass(frozen=True)
class EngineConfig:
    cylinders: int = 4
    initial_rpm: float = 900.0
    inertia: float = .25
    max_rpm: float = 7500.0

    def __post_init__(self):
        if type(self.cylinders) is not int or not 1 <= self.cylinders <= 16:
            raise ValueError('cylinders must be 1..16')
        if not all(math.isfinite(x) for x in (self.initial_rpm, self.inertia, self.max_rpm)):
            raise ValueError('non-finite engine configuration')
        if self.inertia <= 0 or not 0 <= self.initial_rpm <= self.max_rpm <= 20000:
            raise ValueError('invalid engine configuration')

class EngineModel:
    def __init__(self, config=EngineConfig()):
        self.config = config
        self.rpm, self.angle = config.initial_rpm, 0.0
        self.throttle, self.injector_ms, self.ignition_deg = .15, 2.5, 12.0
        self.load_nm, self.target_rpm = 12.0, None
        self.open_injectors, self.charging = {}, {}
        self.last_injection_us, self.last_dwell_us = {}, {}

    def command(self, data):
        allowed = {'throttle', 'injector_ms', 'ignition_deg', 'load_nm', 'rpm', 'idle'}
        if not isinstance(data, dict) or set(data)-allowed:
            raise ValueError('unknown actuator field')
        values = {k: float(v) for k,v in data.items()}
        if not all(math.isfinite(v) for v in values.values()):
            raise ValueError('non-finite actuator value')
        for key, value in values.items():
            bounds = {'throttle': (0,1), 'idle': (0,1), 'injector_ms': (0,100),
                      'ignition_deg': (-180,180), 'load_nm': (0,1000), 'rpm': (0,self.config.max_rpm)}
            low, high = bounds[key]
            if not low <= value <= high:
                raise ValueError('actuator outside range: '+key)
        for key, value in values.items():
            if key == 'rpm':
                self.rpm = self.target_rpm = value  # zkušební stolice s pevnými otáčkami
            elif key == 'idle':
                self.throttle = value
            else:
                setattr(self, key, value)

    def event(self, data):
        signal, action = data.get('signal'), data.get('action')
        channel, timestamp = data.get('channel'), data.get('simulation_time_us')
        if type(channel) is not int or not 0 <= channel < self.config.cylinders:
            raise ValueError('invalid ECU channel')
        if type(timestamp) is not int or timestamp < 0:
            raise ValueError('invalid event time')
        if signal == 'injector' and action in ('start', 'end'):
            active, durations = self.open_injectors, self.last_injection_us
        elif signal == 'ignition' and action in ('charge', 'spark'):
            active, durations = self.charging, self.last_dwell_us
        else:
            raise ValueError('invalid ECU event')
        if action in ('start','charge'):
            if channel in active:
                raise ValueError('duplicate pulse start')
            active[channel] = timestamp
        else:
            if channel not in active or timestamp < active[channel]:
                raise ValueError('unpaired or reversed ECU event')
            durations[channel] = timestamp-active.pop(channel)
            if signal == 'injector':
                self.injector_ms = durations[channel]/1000

    def step(self, dt):
        before = self.rpm
        fuel = max(0, min(1.5, self.injector_ms/3))
        spark = max(.1, 1-abs(self.ignition_deg-15)/80)
        torque = 100*self.config.cylinders/4*self.throttle*fuel*spark
        acceleration = (torque-self.load_nm-5-.005*self.rpm)/self.config.inertia
        self.rpm = (self.target_rpm if self.target_rpm is not None else
                    max(0, min(self.config.max_rpm, self.rpm+acceleration*60/(2*math.pi)*dt)))
        self.angle += (before+self.rpm)/2*6*dt

    def snapshot(self):
        return {'rpm': self.rpm, 'throttle': self.throttle, 'tps': self.throttle,
                'map_kpa': 25+75*self.throttle, 'iat_c': 25.0, 'coolant_c': 85.0,
                'clt_c': 85.0, 'crank_deg': self.angle % 720,
                'crank_angle_deg': self.angle % 360, 'cycle_angle_deg': self.angle % 720,
                'lambda_value': max(.6,min(2,3/max(self.injector_ms,.1))),
                'cylinders': self.config.cylinders,
                'last_injection_us': dict(self.last_injection_us),
                'last_dwell_us': dict(self.last_dwell_us)}
