"""Verzovaný JSON Lines protokol a omezený dekodér rámců."""

import json
import math
import zlib

MAX_FRAME = 16384


def validate(obj):
    if not isinstance(obj, dict):
        raise ValueError("message must be an object")
    required = {
        "version",
        "type",
        "sequence",
        "simulation_time_us",
        "source",
        "data",
        "error",
    }
    if not required <= obj.keys() or type(obj["version"]) is not int or obj["version"] != 1:
        raise ValueError("invalid protocol envelope/version")
    for key in ("sequence", "simulation_time_us"):
        if type(obj[key]) is not int or obj[key] < 0:
            raise ValueError("invalid " + key)
    if obj["type"] not in (
        "engine_state",
        "actuators",
        "ecu_event",
        "signal_events",
        "clock_sync",
        "error",
        "hardware_status",
        "hardware_reset",
        "ecu_events",
    ):
        raise ValueError("unknown message type")
    if not isinstance(obj["source"], str) or not obj["source"] or not isinstance(obj["data"], dict):
        raise ValueError("invalid source/data")
    if obj["error"] is not None and not isinstance(obj["error"], dict):
        raise ValueError("invalid error")

    def finite(value):
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("non-finite number")
        if isinstance(value, dict):
            for v in value.values():
                finite(v)
        if isinstance(value, list):
            for v in value:
                finite(v)

    finite(obj)
    return obj


def message(kind, sequence, time_us, data, source="host", error=None):
    return validate(
        dict(
            version=1,
            type=kind,
            sequence=sequence,
            simulation_time_us=time_us,
            source=source,
            data=data,
            error=error,
        )
    )


def encode(obj, integrity=False):
    base = dict(validate(obj))
    protected = integrity or "integrity" in base
    base.pop("integrity", None)
    raw = json.dumps(base, separators=(",", ":"), allow_nan=False).encode()
    if protected:
        checksum = f"{zlib.crc32(raw):08x}"
        raw = raw[:-1] + b',"integrity":{"crc32":"' + checksum.encode() + b'"}}'
    raw += b"\n"
    if len(raw) > MAX_FRAME:
        raise ValueError("frame too large")
    return raw


def decode(raw):
    if isinstance(raw, str):
        raw = raw.encode()
    if len(raw) > MAX_FRAME:
        raise ValueError("frame too large")
    try:
        obj = validate(json.loads(raw))
        if "integrity" in obj:
            integrity = obj["integrity"]
            if not isinstance(integrity, dict) or set(integrity) != {"crc32"}:
                raise ValueError("invalid integrity field")
            checksum = integrity["crc32"]
            prefix, separator, suffix = raw.strip().rpartition(b',"integrity":')
            if not separator or not isinstance(checksum, str) or len(checksum) != 8:
                raise ValueError("invalid protected frame layout")
            if suffix != ('{"crc32":"' + checksum + '"}}').encode():
                raise ValueError("integrity must be the last canonical field")
            if f"{zlib.crc32(prefix + b'}'):08x}" != checksum.lower():
                raise ValueError("CRC32 mismatch")
        return obj
    except (UnicodeDecodeError, RecursionError) as exc:
        raise ValueError("invalid JSON") from exc


class LineDecoder:
    def __init__(self):
        self.buffer = bytearray()
        self.discarding = False
        self.errors = 0

    def feed(self, chunk):
        result = []
        for byte in chunk:
            if byte == 10:
                if not self.discarding and self.buffer:
                    try:
                        result.append(decode(self.buffer))
                    except (ValueError, RecursionError):
                        self.errors += 1
                self.buffer.clear()
                self.discarding = False
            elif not self.discarding:
                self.buffer.append(byte)
                if len(self.buffer) >= MAX_FRAME:
                    self.buffer.clear()
                    self.discarding = True
                    self.errors += 1
        return result


def expand_events(packet):
    """Rozbalení kompaktní dávky; pořadí i původní čas každé hrany zůstávají zachované."""
    if packet["type"] != "ecu_events":
        return [packet]
    rows = packet["data"].get("events")
    if not isinstance(rows, list) or not 1 <= len(rows) <= 16:
        raise ValueError("invalid event batch")
    result = []
    actions = (
        ("start", "end", "aborted", "invalid", "timeout"),
        ("charge", "spark", "aborted", "invalid", "timeout"),
    )
    for row in rows:
        if (
            not isinstance(row, list)
            or len(row) != 8
            or any(type(value) is not int or value < 0 for value in row)
        ):
            raise ValueError("invalid compact event")
        simulation, ecu, kind, channel, action, duration, angle, error = row
        if kind > 1 or channel > 3 or action > 4 or angle > 720000 or error > 5:
            raise ValueError("compact event outside range")
        data = dict(
            signal="ignition" if kind else "injector",
            action=actions[kind][action],
            channel=channel,
            channel_name=("IGN" if kind else "INJ") + str(channel + 1),
            simulation_time_us=simulation,
            ecu_time_us=ecu,
            duration_us=duration,
            cycle_angle_deg=angle / 1000,
            crank_angle_deg=(angle / 1000) % 360,
            hardware_session=packet["data"]["hardware_session"],
        )
        result.append(
            message(
                "ecu_event",
                packet["sequence"],
                simulation,
                data,
                packet["source"],
                {"code": f"hardware_pulse_{error}"} if error else None,
            )
        )
    return result
