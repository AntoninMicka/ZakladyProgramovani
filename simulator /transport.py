"""Transport nezná fyziku ani JSON. Veškeré I/O běží mimo model."""
import logging
import queue
from threading import Thread, Event, Lock

LOG = logging.getLogger(__name__)

class SerialTransport:
    def __init__(self, url, baudrate=115200):
        self.url, self.baudrate, self.port = url, baudrate, None

    def open(self):
        import serial
        # RFC2217 nepodporuje write_timeout; socket pySerialu má síťový timeout.
        self.port = serial.serial_for_url(self.url, baudrate=self.baudrate, timeout=.02,
                                          do_not_open=True)
        self.port.open()

    def read(self):
        available = self.port.in_waiting
        if available > 65536:
            raise BufferError("serial input backlog exceeded 64 KiB")
        return self.port.read(max(1,min(available,4096)))

    def write(self, raw):
        self.port.write(raw)

    def close(self):
        if self.port is not None:
            self.port.close()

class ConnectionWorker(Thread):
    def __init__(self, factory, receiver, retry=.5, capacity=4, on_connect=None, on_disconnect=None):
        super().__init__(name='wokwi-transport',daemon=False)
        self.factory, self.receiver, self.retry = factory, receiver, retry
        self.on_connect = on_connect or (lambda: None)
        self.on_disconnect = on_disconnect or (lambda: None)
        self.outgoing = queue.Queue(capacity)
        self.stop_event, self.connected = Event(), Event()
        self.lock, self.transport = Lock(), None
        self.reconnects, self.errors, self.dropped = 0,0,0
        self.generation = 0

    def send(self, raw):
        if not self.connected.is_set():
            self.dropped += 1
            return False
        try: self.outgoing.put_nowait(raw)
        except queue.Full:
            self.dropped += 1
            return False
        return True

    def _clear(self):
        while True:
            try: self.outgoing.get_nowait()
            except queue.Empty: break

    def run(self):
        while not self.stop_event.is_set():
            transport = None
            try:
                transport = self.factory()
                with self.lock: self.transport = transport
                transport.open()
                if self.stop_event.is_set(): break
                self._clear()
                self.generation += 1
                self.on_connect()
                self.connected.set()
                self.reconnects += 1
                while not self.stop_event.is_set():
                    try: raw = self.outgoing.get_nowait()
                    except queue.Empty: raw = None
                    if raw is not None: transport.write(raw)
                    chunk = transport.read()
                    if chunk: self.receiver(chunk)
            except Exception as exc:
                if not self.stop_event.is_set():
                    self.errors += 1
                    LOG.warning('Serial connection lost/unavailable: %s; retry in %.2fs',exc,self.retry)
            finally:
                if self.connected.is_set(): self.on_disconnect()
                self.connected.clear()
                self._clear()
                try:
                    if transport is not None: transport.close()
                except Exception: LOG.exception('Transport close failed')
                with self.lock: self.transport = None
            self.stop_event.wait(self.retry)

    def close(self):
        self.stop_event.set()
        # Přerušení čtení/zápisu uzavřením socketu; během vyjednávání čekáme na timeout pySerialu.
        with self.lock: transport = self.transport
        if transport:
            try: transport.close()
            except Exception: LOG.debug('Concurrent transport close',exc_info=True)
        if self.ident is not None:
            self.join(timeout=20)
            if self.is_alive():
                raise RuntimeError('transport did not stop within 20 seconds')
