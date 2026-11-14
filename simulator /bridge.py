"""Aplikační bridge; transport a fyzikální model komunikují pouze přes rozhraní."""
import logging
from time import monotonic
from threading import Lock
from protocol import message, encode, LineDecoder
from transport import SerialTransport, ConnectionWorker

LOG = logging.getLogger(__name__)

class Bridge:
    def __init__(self, engine):
        self.engine = engine
        self.sequence = 0
        self.metrics = {'received':0,'invalid':0,'rtt_us':None,'ecu_offset_us':None,
                        'ecu_drift_us':None,'ecu_time_us':None}
        self.pending = {}
        self.offset_baseline = None
        self.lock = Lock()

    def packet(self, kind, data, time_us=None):
        self.sequence += 1
        return message(kind,self.sequence,self.engine.snapshot()['simulation_time_us'] if time_us is None else time_us,data)

    def receive(self, obj):
        try:
            if obj.get('error'):
                raise ValueError('ECU reported error: '+str(obj['error']))
            kind, data = obj.get('type'), obj.get('data',obj)
            if kind == 'actuators':
                self.engine.command(data)
            elif kind == 'ecu_event':
                self.engine.ecu_event(data)
            elif kind == 'clock_sync':
                with self.lock:
                    echo = data.get('echo_sequence')
                    sent = self.pending.pop(echo,None)
                    ecu_us = data.get('ecu_time_us')
                    if sent is None or type(ecu_us) is not int or ecu_us < 0:
                        raise ValueError('invalid clock echo')
                    wall, sim = sent
                    rtt = round((monotonic()-wall)*1e6)
                    # Není převod hodin: jen pozorovaný offset mezi nesynchronními osami.
                    offset = ecu_us-sim
                    if self.offset_baseline is None: self.offset_baseline = offset
                    self.metrics.update(rtt_us=rtt,ecu_offset_us=offset,
                                        ecu_drift_us=offset-self.offset_baseline,ecu_time_us=ecu_us)
            else:
                raise ValueError('unexpected ECU message type')
            self.metrics['received'] += 1
        except (ValueError, TypeError, BufferError, KeyError) as exc:
            self.metrics['invalid'] += 1
            LOG.warning('Rejected ECU message: %s',exc)

    def sensors(self):
        return {'type':'sensors',**self.engine.snapshot()}

    def start(self): pass
    def close(self): pass

class MockBridge(Bridge):
    """Uzavřená smyčka bez sítě; stejné aplikační rozhraní jako ECU."""
    def tick(self):
        state = self.engine.snapshot()
        injection = max(.5,min(6,2.7+.002*(1200-state['rpm'])))
        self.receive(message('actuators',self.sequence,state['simulation_time_us'],
                             {'injector_ms':injection,'ignition_deg':15},source='mock'))
        self.sequence += 1
        self.engine.drain_events(4096)
        return self.sensors()

class RFC2217Bridge(Bridge):
    def __init__(self, engine, url, baudrate=115200, transport_factory=None, retry=.5):
        super().__init__(engine)
        self.decoder = LineDecoder()
        self.worker = ConnectionWorker(transport_factory or (lambda:SerialTransport(url,baudrate)),
                                       self._receive_bytes,retry=retry,on_connect=self._new_connection,
                                       on_disconnect=self.engine.invalidate)
        self.last_state = None

    def _new_connection(self):
        self.decoder = LineDecoder()
        with self.lock:
            self.pending.clear()
            self.offset_baseline = None

    def _receive_bytes(self, chunk):
        for obj in self.decoder.feed(chunk): self.receive(obj)

    def start(self): self.worker.start()

    def tick(self):
        state = self.engine.snapshot()
        packet = self.packet('engine_state',state,state['simulation_time_us'])
        with self.lock:
            self.pending[packet['sequence']] = (monotonic(),state['simulation_time_us'])
            while len(self.pending) > 64: self.pending.pop(next(iter(self.pending)))
        self.worker.send(encode(packet))
        # Hrany zůstávají lokální diagnostikou. 60-2 při vysokých RPM překračuje
        # kapacitu UART 115200; jednotlivé hrany neposíláme přes JSON/TCP.
        self.engine.drain_events(4096)
        return {'type':'sensors',**state}

    def diagnostics(self):
        return {**self.metrics,'connected':self.worker.connected.is_set(),
                'connections':self.worker.reconnects,'transport_errors':self.worker.errors,
                'dropped_frames':self.worker.dropped,'invalid_frames':self.decoder.errors}

    def close(self): self.worker.close()
