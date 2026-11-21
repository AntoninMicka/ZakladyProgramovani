"""Životní cyklus aplikace, bez fyzikálních výpočtů."""

from threading import Event, RLock
from engine import Engine
from bridge import MockBridge, RFC2217Bridge
from model import EngineConfig


class Supervisor:
    def __init__(
        self,
        mode="mock",
        url="rfc2217://localhost:4000",
        dt=0.001,
        speed=1,
        config=EngineConfig(),
        signals=None,
        baudrate=115200,
        hardware=False,
        hardware_mode="buffered",
        lookahead_us=100000,
        vehicle=False,
    ):
        self.mode, self.url, self.baudrate = mode, url, baudrate
        self.hardware_options = dict(
            hardware=hardware, hardware_mode=hardware_mode, lookahead_us=lookahead_us
        )
        self.transport_factory = None
        self.lifecycle_lock = RLock()
        self.closing = Event()
        self.engine = Engine(dt=dt, speed=speed, config=config, signals=signals, vehicle=vehicle)
        self.initial_commands = {
            "throttle": self.engine.model.throttle,
            "load_nm": self.engine.model.load_nm,
            "rpm": None,
        }
        self.bridge = self._bridge(mode, url, baudrate, self.hardware_options, None)

    def _bridge(self, mode, url, baudrate, options, transport_factory):
        if mode == "mock":
            return MockBridge(self.engine)
        if mode != "wokwi":
            raise ValueError("Unsupported backend: " + mode)
        return RFC2217Bridge(
            self.engine, url, baudrate, transport_factory=transport_factory, **options
        )

    def configure_initial(self, commands):
        if self.engine.ident is not None:
            raise RuntimeError("Initial configuration must precede start")
        self.engine.model.command(commands)
        self.initial_commands.update(commands)

    def start(self):
        self.engine.start()
        try:
            self.bridge.start()
        except Exception:
            self.engine.stop()
            self.engine.join()
            raise

    def pause(self):
        self.engine.pause()

    def resume(self):
        self.engine.resume()

    def switch_backend(
        self,
        mode,
        url="rfc2217://localhost:4000",
        baudrate=115200,
        hardware=False,
        hardware_mode="buffered",
        lookahead_us=100000,
        transport_factory=None,
        config=None,
        signals=None,
        reset=False,
        paused=True,
        initial_commands=None,
    ):
        """Volat mimo Tk vlákno: uzavření síťového backendu může čekat na timeout."""
        options = dict(hardware=hardware, hardware_mode=hardware_mode, lookahead_us=lookahead_us)
        new_bridge = self._bridge(mode, url, baudrate, options, transport_factory)
        with self.lifecycle_lock:
            if self.closing.is_set():
                raise RuntimeError("Aplikace se ukončuje")
            previous = self.engine.snapshot()
            self.engine.pause()
            self.bridge.close()
            if self.closing.is_set():
                raise RuntimeError("Aplikace se ukončuje")
            with self.engine.lock:
                if config is not None:
                    self.engine.config = config
                if signals is not None:
                    self.engine.signals = signals
                if reset:
                    self.engine.reset()
                self.engine.invalidate()
                initial = {
                    "throttle": previous["throttle"],
                    "load_nm": previous["load_nm"],
                }
                if reset and previous["fixed_rpm"] is not None:
                    initial["rpm"] = previous["fixed_rpm"]
                self.engine.command(initial_commands if initial_commands is not None else initial)
            self.mode, self.url, self.baudrate = mode, url, baudrate
            self.hardware_options, self.transport_factory = options, transport_factory
            self.bridge = new_bridge
            try:
                new_bridge.start()
            except Exception:
                self.mode = "mock"
                self.transport_factory = None
                self.bridge = MockBridge(self.engine)
                self.bridge.start()
                raise
            if not paused:
                self.engine.resume()

    def apply_mock_ecu(self, controller):
        """Hotový překlad vyměníme až pod zámkem. Chyba překladu sem vůbec nedojde."""
        with self.lifecycle_lock, self.engine.lock:
            if self.mode != "mock" or self.closing.is_set():
                raise RuntimeError("Mock už není aktivní; nová ECU nebyla použita.")
            previous = self.engine.snapshot()
            was_paused = self.engine.paused
            self.engine.pause()
            self.bridge.close()
            self.engine.reset()
            self.engine.model.command(
                {
                    "throttle": previous["throttle"],
                    "load_nm": previous["load_nm"],
                    "rpm": previous["fixed_rpm"],
                }
            )
            self.bridge = MockBridge(self.engine, controller)
            self.bridge.start()
            if not was_paused:
                self.engine.resume()

    def restart(self):
        self.switch_backend(
            self.mode,
            self.url,
            self.baudrate,
            **self.hardware_options,
            transport_factory=self.transport_factory,
            reset=True,
            paused=False,
            initial_commands=self.initial_commands,
        )

    def close(self):
        self.closing.set()
        self.engine.stop()
        with self.lifecycle_lock:
            try:
                self.bridge.close()
            finally:
                if self.engine.ident is not None:
                    self.engine.join(timeout=2)
                if self.engine.is_alive():
                    raise RuntimeError("engine failed to stop")
