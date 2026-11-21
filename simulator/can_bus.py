"""Deterministická výuková CAN 2.0A: 11bit ID, 8 B, priorita a čas přenosu.

Jde o lokální logickou sběrnici, nikoli emulaci transceiveru nebo SocketCAN.
Doba rámce používá konzervativní počet bitů místo bitového stuffing/CRC modelu.
"""

import heapq
import math
import struct
from collections import deque
from dataclasses import dataclass

# Vlastní výukový protokol, little endian; žádná výrobní automobilová DBC.
SCHEMAS = {
    0x100: ("ECU", "<HHhH", ("rpm", "fuel_us", "torque_nm", "pedal_permille")),
    0x110: ("SENSORS", "<hhhh", ("fl_cms", "fr_cms", "rl_cms", "rr_cms")),
    0x120: ("CHASSIS", "<hhhh", ("speed_cms", "yaw_mrad_s", "steer_mrad", "brake_permille")),
    0x130: ("SELECTOR", "<B", ("selector",)),
    0x200: ("TCU", "<bB", ("gear", "shifting")),
    0x210: ("ABS_ESP", "<BBBBBBBB", ("fl", "fr", "rl", "rr", "abs", "esp", "torque_pct", "fault")),
    0x300: ("THERMAL", "<hhHH", ("coolant_dc", "oil_dc", "oil_kpa", "battery_cv")),
    0x310: ("BODY", "<HHhh", ("fuel_permille", "maf_dgs", "ax_cms2", "ay_cms2")),
}


def encode(identifier, **values):
    _, fmt, fields = SCHEMAS[identifier]
    if set(values) != set(fields):
        raise ValueError("CAN: nesprávná pole zprávy")
    return struct.pack(fmt, *(values[f] for f in fields))


def decode(identifier, data):
    _, fmt, fields = SCHEMAS[identifier]
    return dict(zip(fields, struct.unpack(fmt, data)))


@dataclass(frozen=True)
class Frame:
    identifier: int
    data: bytes
    sender: str
    time_us: int

    def __post_init__(self):
        if type(self.identifier) is not int or not 0 <= self.identifier <= 0x7FF:
            raise ValueError("CAN: ID musí být 11bitové")
        if not isinstance(self.data, bytes) or len(self.data) > 8:
            raise ValueError("CAN: nejvýše 8 datových bajtů")
        if type(self.time_us) is not int or self.time_us < 0:
            raise ValueError("CAN: neplatný čas")


class CanBus:
    def __init__(self, bitrate=500_000, capacity=256, history=120):
        if type(bitrate) is not int or not 1_000 <= bitrate <= 1_000_000:
            raise ValueError("CAN: neplatný bitrate")
        if type(capacity) is not int or capacity < 1 or type(history) is not int or history < 1:
            raise ValueError("CAN: neplatná kapacita")
        self.bitrate, self.capacity = bitrate, capacity
        self.pending = []
        self.waiting = []
        self.history = deque(maxlen=history)
        self.latest = {}
        self.sequence = self.time_us = self.busy_until = 0
        self.in_flight = None
        self.started_us = 0
        self.enabled = True
        self.sent = self.delivered = self.dropped = self.bits = 0

    def send(self, identifier, data, sender, now):
        frame = Frame(identifier, data, sender, now)
        if now < self.time_us:
            raise ValueError("CAN: nelze odeslat do minulosti")
        if not self.enabled or len(self.pending) + len(self.waiting) >= self.capacity:
            self.dropped += 1
            return False
        self.sequence += 1
        heapq.heappush(self.pending, (now, self.sequence, frame))
        self.sent += 1
        return True

    def advance(self, end_us):
        if end_us < self.time_us:
            raise ValueError("CAN: čas se nesmí vracet")
        if not self.enabled:
            self.dropped += len(self.pending) + len(self.waiting) + bool(self.in_flight)
            self.pending.clear()
            self.waiting.clear()
            self.in_flight = None
            self.time_us = self.busy_until = end_us
            return
        cursor = self.time_us
        while True:
            if self.in_flight:
                if self.busy_until > end_us:
                    break
                cursor = self.busy_until
                f = self.in_flight
                delivered = Frame(f.identifier, f.data, f.sender, cursor)
                self.latest[f.identifier] = delivered
                self.history.append(delivered)
                self.delivered += 1
                self.in_flight = None
            while self.pending and self.pending[0][0] <= cursor:
                _, seq, frame = heapq.heappop(self.pending)
                heapq.heappush(self.waiting, (frame.identifier, seq, frame))
            if not self.waiting:
                if not self.pending or self.pending[0][0] > end_us:
                    break
                cursor = max(cursor, self.pending[0][0])
                continue
            if cursor >= end_us:
                break
            _, _, frame = heapq.heappop(self.waiting)
            self.in_flight = frame
            bits = 67 + len(frame.data) * 10  # Včetně rezervy pro stuffing a intermission.
            self.bits += bits
            self.busy_until = cursor + math.ceil(bits * 1_000_000 / self.bitrate)
        self.time_us = end_us

    def read(self, identifier, now, max_age_us=300_000):
        frame = self.latest.get(identifier)
        if frame is None or now - frame.time_us > max_age_us:
            return None
        return decode(identifier, frame.data)

    def snapshot(self):
        return {
            "enabled": self.enabled,
            "bitrate": self.bitrate,
            "sent": self.sent,
            "delivered": self.delivered,
            "dropped": self.dropped,
            "queue_depth": len(self.pending) + len(self.waiting) + bool(self.in_flight),
            "utilization_pct": min(
                100, self.bits / max(1, (self.time_us - self.started_us) * self.bitrate / 1e6) * 100
            ),
            "frames": [
                {
                    "time_us": f.time_us,
                    "id": f.identifier,
                    "sender": f.sender,
                    "hex": f.data.hex(" "),
                    "signals": decode(f.identifier, f.data) if f.identifier in SCHEMAS else {},
                }
                for f in self.history
            ],
        }
