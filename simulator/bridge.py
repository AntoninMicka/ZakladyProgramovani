"""Aplikační bridge; transport a fyzikální model komunikují pouze přes rozhraní."""

import logging
import secrets
import math
from time import monotonic
from threading import Lock
from protocol import message, encode, LineDecoder, expand_events
from transport import SerialTransport, ConnectionWorker

LOG = logging.getLogger(__name__)


class Bridge:
    def __init__(self, engine):
        self.engine = engine
        self.sequence = 0
        self.metrics = {
            "received": 0,
            "invalid": 0,
            "rtt_us": None,
            "ecu_offset_us": None,
            "ecu_drift_us": None,
            "ecu_time_us": None,
            "hardware": None,
            "hardware_resets": 0,
            "hardware_sequence_gaps": 0,
        }
        self.pending = {}
        self.offset_baseline = None
        self.lock = Lock()

    def packet(self, kind, data, time_us=None):
        self.sequence += 1
        return message(
            kind,
            self.sequence,
            self.engine.snapshot()["simulation_time_us"] if time_us is None else time_us,
            data,
        )

    def receive(self, obj):
        try:
            if obj.get("error"):
                raise ValueError("ECU reported error: " + str(obj["error"]))
            kind, data = obj.get("type"), obj.get("data", obj)
            if kind == "ecu_events":
                for event in expand_events(obj):
                    if event["data"]["action"] in ("aborted", "timeout"):
                        self.engine.invalidate()
                    Bridge.receive(self, event)
                return
            if kind == "actuators":
                self.engine.command(data)
            elif kind == "ecu_event":
                self.engine.ecu_event(data)
            elif kind == "hardware_status":
                if type(data.get("running")) is not bool:
                    raise ValueError("invalid hardware run state")
                for key in (
                    "queue_depth",
                    "late_updates",
                    "crc_errors",
                    "dropped_tx",
                    "watchdog_timeouts",
                ):
                    if type(data.get(key)) is not int or data[key] < 0:
                        raise ValueError("invalid hardware counter: " + key)
                if (
                    data["queue_depth"] > 64
                    or type(data.get("phase_error_deg")) not in (int, float)
                    or not math.isfinite(data["phase_error_deg"])
                    or abs(data["phase_error_deg"]) > 360
                ):
                    raise ValueError("invalid hardware queue/phase")
                previous = self.metrics["hardware"]
                if previous and data["dropped_tx"] > previous["dropped_tx"]:
                    self.engine.invalidate()
                    LOG.warning(
                        "Virtual hardware lost event frames; pending ECU outputs invalidated"
                    )
                self.metrics["hardware"] = dict(data)
            elif kind == "clock_sync":
                with self.lock:
                    echo = data.get("echo_sequence")
                    sent = self.pending.pop(echo, None)
                    ecu_us = data.get("ecu_time_us")
                    if sent is None or type(ecu_us) is not int or ecu_us < 0:
                        raise ValueError("invalid clock echo")
                    wall, sim = sent
                    rtt = round((monotonic() - wall) * 1e6)
                    # Není převod hodin: jen pozorovaný offset mezi nesynchronními osami.
                    offset = ecu_us - sim
                    if self.offset_baseline is None:
                        self.offset_baseline = offset
                    self.metrics.update(
                        rtt_us=rtt,
                        ecu_offset_us=offset,
                        ecu_drift_us=offset - self.offset_baseline,
                        ecu_time_us=ecu_us,
                    )
            else:
                raise ValueError("unexpected ECU message type")
            self.metrics["received"] += 1
        except (ValueError, TypeError, BufferError, KeyError) as exc:
            self.metrics["invalid"] += 1
            LOG.warning("Rejected ECU message: %s", exc)

    def diagnostics(self):
        return dict(self.metrics)

    def sensors(self):
        return {"type": "sensors", **self.engine.snapshot()}

    def start(self):
        pass

    def close(self):
        pass


class MockBridge(Bridge):
    """Lokální GPIO/časovačový adaptér stejného C++ řadiče jako ve firmware."""

    def __init__(self, engine, controller=None):
        super().__init__(engine)
        from native_ecu import NativeEcu

        self.controller = controller or NativeEcu(engine.config, engine.signals)
        self.started = False

    def start(self):
        with self.engine.lock:
            self.controller.reset(self.engine.clock.time_us, self.engine.model.throttle)
            self.engine.local_ecu = self.controller
            self.started = True

    def tick(self):
        if not self.started:
            self.start()
        self.diagnostics()
        return self.sensors()

    def diagnostics(self):
        with self.engine.lock:
            ecu = self.controller.diagnostics()
            self.metrics["received"] = ecu["events"]
            return {**self.metrics, "controller": ecu}

    def close(self):
        with self.engine.lock:
            if self.engine.local_ecu is self.controller:
                self.engine.local_ecu = None
            self.controller.close()
            self.started = False


class RFC2217Bridge(Bridge):
    def __init__(
        self,
        engine,
        url,
        baudrate=115200,
        transport_factory=None,
        retry=0.5,
        hardware=False,
        hardware_mode="buffered",
        lookahead_us=100000,
    ):
        super().__init__(engine)
        if hardware_mode not in ("buffered", "free") or not 1000 <= lookahead_us <= 1000000:
            raise ValueError("invalid hardware synchronization configuration")
        self.hardware, self.hardware_mode, self.lookahead_us = (
            hardware,
            hardware_mode,
            lookahead_us,
        )
        self.hardware_session = secrets.randbits(32)
        self.last_hardware_time = None
        self.last_hardware_sequence = None
        self.decoder = LineDecoder()
        self.worker = ConnectionWorker(
            transport_factory or (lambda: SerialTransport(url, baudrate)),
            self._receive_bytes,
            retry=retry,
            on_connect=self._new_connection,
            on_disconnect=self.engine.invalidate,
        )
        self.last_state = None

    def _new_connection(self):
        self.hardware_session = secrets.randbits(32)
        self.last_hardware_time = None
        self.last_hardware_sequence = None
        self.decoder = LineDecoder()
        with self.lock:
            self.pending.clear()
            self.offset_baseline = None

    def receive(self, obj):
        if self.hardware and (
            obj.get("source") != "engine-interface"
            or "integrity" not in obj
            or obj.get("data", {}).get("hardware_session") != self.hardware_session
        ):
            self.metrics["invalid"] += 1
            return
        if self.hardware:
            if obj.get("type") == "ecu_event" and obj.get("data", {}).get("action") in (
                "aborted",
                "timeout",
            ):
                self.engine.invalidate()
            sequence = obj["sequence"]
            if self.last_hardware_sequence is not None:
                if sequence < self.last_hardware_sequence:
                    self.engine.invalidate()
                    self.metrics["hardware_resets"] += 1
                    self.metrics["hardware"] = None
                    self.offset_baseline = None
                    LOG.warning("Virtual hardware restarted; old ECU outputs invalidated")
                elif sequence == self.last_hardware_sequence:
                    self.metrics["invalid"] += 1
                    return
                elif sequence > self.last_hardware_sequence + 1:
                    self.metrics["hardware_sequence_gaps"] += (
                        sequence - self.last_hardware_sequence - 1
                    )
            self.last_hardware_sequence = sequence
        super().receive(obj)

    def _receive_bytes(self, chunk):
        for obj in self.decoder.feed(chunk):
            self.receive(obj)

    def start(self):
        self.worker.start()

    def tick(self):
        state = self.engine.snapshot()
        if self.hardware:
            # Stejný čas při pause není novým segmentem; neroste fronta chipu.
            if state["simulation_time_us"] == self.last_hardware_time:
                return {"type": "sensors", **state}
            state["hardware"] = {
                "session": self.hardware_session,
                "mode": self.hardware_mode,
                "lookahead_us": self.lookahead_us,
            }
        state["bridge_epoch"] = self.hardware_session
        state["simulation_speed"] = self.engine.speed
        # CAN historie a palubní deska patří lokálnímu GUI, nikoli UART protokolu MCU.
        wire_state = {key: value for key, value in state.items() if key != "vehicle"}
        packet = self.packet("engine_state", wire_state, state["simulation_time_us"])
        with self.lock:
            self.pending[packet["sequence"]] = (
                monotonic(),
                state["simulation_time_us"],
            )
            while len(self.pending) > 64:
                self.pending.pop(next(iter(self.pending)))
        if self.worker.send(encode(packet, integrity=self.hardware)) and self.hardware:
            self.last_hardware_time = state["simulation_time_us"]
        # Hrany zůstávají lokální diagnostikou. 60-2 při vysokých RPM překračuje
        # kapacitu UART 115200; jednotlivé hrany neposíláme přes JSON/TCP.
        return {"type": "sensors", **state}

    def diagnostics(self):
        return {
            **self.metrics,
            "connected": self.worker.connected.is_set(),
            "connections": self.worker.reconnects,
            "transport_errors": self.worker.errors,
            "dropped_frames": self.worker.dropped,
            "invalid_frames": self.decoder.errors,
        }

    def close(self):
        self.worker.close()
