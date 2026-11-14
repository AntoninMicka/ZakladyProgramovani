"""JSON Lines bridge. MCU sends {\"type\":\"actuators\", ...} and receives sensor frames."""
import json
import logging
import queue
import threading

LOG = logging.getLogger(__name__)

class Bridge:
    def __init__(self, engine):
        self.engine = engine

    def receive(self, obj):
        if obj.get('type') == 'actuators':
            self.engine.command(obj)
        else:
            LOG.debug('Ignored message: %s', obj)

    def sensors(self):
        return {'type': 'sensors', **self.engine.snapshot()}

class MockBridge(Bridge):
    """Simple mock ECU closed loop; makes simulator usable without Wokwi."""
    def tick(self):
        state = self.engine.snapshot()
        error = 1200.0 - state['rpm']
        injection = max(0.5, min(6.0, 2.7 + 0.002 * error))
        self.receive({'type': 'actuators', 'injector_ms': injection, 'ignition_deg': 15.0})
        return self.sensors()

class RFC2217Bridge(Bridge):
    def __init__(self, engine, url, baudrate=115200):
        super().__init__(engine)
        import serial
        self.port = serial.serial_for_url(url, baudrate=baudrate, timeout=0.05, write_timeout=0.2)
        self.stop_event = threading.Event()
        self.reader = threading.Thread(target=self._read_loop, name='wokwi-reader', daemon=True)

    def start(self):
        self.reader.start()

    def _read_loop(self):
        while not self.stop_event.is_set():
            try:
                raw = self.port.readline()
                if raw:
                    self.receive(json.loads(raw.decode('utf-8')))
            except (ValueError, UnicodeDecodeError) as exc:
                LOG.warning('Invalid ECU JSON: %s', exc)
            except Exception:
                if not self.stop_event.is_set():
                    LOG.exception('Serial receive failed')
                    self.stop_event.set()

    def tick(self):
        frame = self.sensors()
        if self.stop_event.is_set():
            raise ConnectionError('Wokwi serial connection failed')
        self.port.write((json.dumps(frame, separators=(',', ':')) + '\n').encode())
        return frame

    def close(self):
        self.stop_event.set()
        self.port.close()
        self.reader.join(timeout=1)
