import queue
import threading
import unittest
from clock import SimulationClock
from model import EngineModel,EngineConfig
from engine import Engine
from signals import SignalGenerator
from protocol import message,encode,decode,LineDecoder,MAX_FRAME
from bridge import MockBridge,RFC2217Bridge
from transport import ConnectionWorker
from supervisor import Supervisor

class CoreTests(unittest.TestCase):
    def test_clock(self):
        c=SimulationClock(333)
        for _ in range(10000): c.advance()
        self.assertEqual(c.time_us,3330000)
        c.reset();self.assertEqual(c.time_us,0)

    def test_crank_and_cycle(self):
        e=Engine();e.command({'rpm':1000})
        for _ in range(100):e.step()
        self.assertAlmostEqual(e.snapshot()['crank_angle_deg'],240)
        self.assertAlmostEqual(e.snapshot()['cycle_angle_deg'],600)
        self.assertEqual(e.clock.time_us,100000)

    def test_ckp_60_2(self):
        edges=SignalGenerator().edges(-.001,360,0,60000)
        rising=[e for e in edges if e.signal=='CKP' and e.level]
        self.assertEqual(len(rising),59) # včetně 0 a následující 360
        gaps=[b.simulation_time_us-a.simulation_time_us for a,b in zip(rising,rising[1:])]
        self.assertEqual(gaps[-1],3000)
        self.assertTrue(all(abs(t-1000)<=1 for t in gaps[:-1]))
        self.assertEqual(sum(e.signal=='CKP' and not e.level for e in edges),58)

    def test_cmp_720_multiple(self):
        edges=SignalGenerator(cmp_positions=(30,420)).edges(0,1440,0,240000)
        self.assertEqual([e.simulation_time_us for e in edges if e.signal=='CMP' and e.level],
                         [5000,70000,125000,190000])

    def test_edges_split_and_stopped(self):
        g=SignalGenerator()
        self.assertEqual(g.edges(0,720,0,120000),g.edges(0,360,0,60000)+g.edges(360,720,60000,120000))
        self.assertEqual(g.edges(0,0,0,1000),())

    def test_rpm_changes(self):
        e=Engine();e.command({'rpm':1000});e.step();a=e.model.angle
        e.command({'rpm':2000});e.step()
        self.assertAlmostEqual(a,6);self.assertAlmostEqual(e.model.angle-a,12)

    def test_torque_load(self):
        a,b=EngineModel(),EngineModel()
        a.command({'throttle':.5,'load_nm':0});b.command({'throttle':.5,'load_nm':100})
        for _ in range(100):a.step(.001);b.step(.001)
        self.assertGreater(a.rpm,b.rpm);self.assertGreaterEqual(b.rpm,0)

    def test_pulses(self):
        e=Engine(dt=.01)
        for signal,actions,end in [('injector',('start','end'),4500),('ignition',('charge','spark'),3000)]:
            for action,t in zip(actions,(1000,end)):
                e.ecu_event(dict(signal=signal,action=action,channel=2,simulation_time_us=t))
        e.step()
        self.assertEqual(e.model.last_injection_us,{2:3500})
        self.assertEqual(e.model.last_dwell_us,{2:2000})
        self.assertEqual(e.model.injector_ms,3.5)

    def test_future_order_and_late(self):
        e=Engine(dt=.01)
        for t,action in [(25000,'end'),(20000,'start')]:
            e.ecu_event(dict(signal='injector',action=action,channel=0,simulation_time_us=t))
        e.step();self.assertFalse(e.model.open_injectors)
        e.step();self.assertEqual(e.model.open_injectors,{0:20000})
        e.step();self.assertEqual(e.model.last_injection_us,{0:5000})
        e.ecu_event(dict(signal='ignition',action='charge',channel=0,simulation_time_us=0))
        e.step();self.assertEqual(e.diagnostics['late_events'],1)
        self.assertEqual(e.diagnostics['max_lateness_us'],30000)

    def test_reject_invalid(self):
        e=Engine()
        for d in [{'rpm':float('nan')},{'throttle':2},{'unknown':1}]:e.command(d)
        e.ecu_event(dict(signal='injector',action='end',channel=0,simulation_time_us=0))
        e.ecu_event(dict(signal='injector',action='start',channel=99,simulation_time_us=0))
        e.step();self.assertEqual(e.diagnostics['rejected_commands'],5)

    def test_bounded(self):
        e=Engine(capacity=2,dt=.1)
        e.command({'rpm':6000});e.command({'load_nm':1})
        with self.assertRaises(BufferError):e.command({'load_nm':2})
        e.step();self.assertEqual(e.events.qsize(),2);self.assertGreater(e.diagnostics['dropped_events'],0)

    def test_disconnect_discards_old_keeps_new_commands(self):
        e=Engine()
        e.command({'load_nm':100})
        e.ecu_event(dict(signal='injector',action='start',channel=0,simulation_time_us=10000))
        e.invalidate()
        e.command({'load_nm':25})
        e.step()
        self.assertEqual(e.model.load_nm,25)
        self.assertEqual(e.model.injector_ms,0)
        self.assertFalse(e.pending)

    def test_pause_reset(self):
        e=Engine();e.pause();e.step();self.assertEqual(e.clock.time_us,0)
        e.resume();e.step();self.assertEqual(e.clock.time_us,1000)
        e.reset();self.assertEqual(e.clock.time_us,0)

    def test_mock_closed_loop(self):
        e=Engine();e.command({'throttle':.35});b=MockBridge(e)
        for _ in range(2000):
            if e.clock.time_us%50000==0:b.tick()
            e.step()
        self.assertGreater(e.snapshot()['rpm'],900)
        self.assertLess(abs(e.snapshot()['rpm']-1200),300)
        self.assertEqual(b.metrics['invalid'],0)

    def test_thread_shutdown(self):
        e=Engine();e.start();e.pause();e.stop();e.join(1);self.assertFalse(e.is_alive())

    def test_supervisor_restart(self):
        a=Supervisor();a.start()
        try:a.pause();a.restart()
        finally:a.close()
        self.assertFalse(a.engine.is_alive())

    def test_config(self):
        for args in [dict(cylinders=0),dict(inertia=0),dict(initial_rpm=float('nan'))]:
            with self.assertRaises(ValueError):EngineConfig(**args)
        for args in [dict(teeth=1,missing=2),dict(cmp_positions=(10,11)),dict(cmp_positions=(720,))]:
            with self.assertRaises(ValueError):SignalGenerator(**args)

class ProtocolTests(unittest.TestCase):
    def test_roundtrip(self):
        m=message('engine_state',1,25000,{'rpm':1500});self.assertEqual(decode(encode(m)),m)

    def test_framing(self):
        d=LineDecoder();raw=encode(message('actuators',1,0,{'load_nm':2}))
        self.assertEqual(d.feed(raw[:8]),[]);self.assertEqual(len(d.feed(raw[8:])),1)
        self.assertEqual(d.feed(b'bad\n'+b'x'*(MAX_FRAME+2)+b'\n'),[])
        self.assertEqual(d.errors,2);self.assertEqual(len(d.feed(raw)),1)

    def test_invalid(self):
        m=message('actuators',1,0,{})
        for k,v in [('version',2),('sequence',True),('simulation_time_us',-1),('data',[]),('source',''),('type','unknown')]:
            with self.subTest(k=k),self.assertRaises(ValueError):encode({**m,k:v})
        for raw in [b'[]',b'null',b'{"version":1}',b'\xff',b'{']:
            with self.assertRaises(ValueError):decode(raw)
        with self.assertRaises(ValueError):message('actuators',1,0,{'rpm':float('nan')})

class FakeTransport:
    def __init__(self,incoming,sent):self.incoming,self.sent=incoming,sent
    def open(self):pass
    def write(self,raw):self.sent.put(raw)
    def read(self):
        try:raw=self.incoming.get(timeout=.01)
        except queue.Empty:return b''
        if raw is None:raise OSError('scripted disconnect')
        return raw
    def close(self):pass

class CommunicationTests(unittest.TestCase):
    def test_reconnect(self):
        incoming,sent,connections=queue.Queue(),queue.Queue(),queue.Queue()
        received=threading.Event()
        def factory():connections.put(1);return FakeTransport(incoming,sent)
        w=ConnectionWorker(factory,lambda raw:received.set(),retry=.001)
        w.start()
        try:
            self.assertTrue(w.connected.wait(1));self.assertTrue(w.send(b'hello'))
            self.assertEqual(sent.get(timeout=1),b'hello')
            incoming.put(None);connections.get(timeout=1);connections.get(timeout=1)
            self.assertTrue(w.connected.wait(1));incoming.put(b'reply')
            self.assertTrue(received.wait(1));self.assertGreaterEqual(w.reconnects,2)
        finally:w.close()
        self.assertFalse(w.is_alive())

    def test_offline_bounded(self):
        w=ConnectionWorker(lambda:None,lambda raw:None,capacity=2)
        for _ in range(100):w.send(b'x')
        self.assertEqual(w.outgoing.qsize(),0);self.assertEqual(w.dropped,100)
        w.connected.set()
        for _ in range(100):w.send(b'x')
        self.assertEqual(w.outgoing.qsize(),2);w.close()

    def test_bridge_both_directions(self):
        e=Engine();incoming,sent=queue.Queue(),queue.Queue()
        b=RFC2217Bridge(e,'unused',transport_factory=lambda:FakeTransport(incoming,sent))
        b.start()
        try:
            self.assertTrue(b.worker.connected.wait(1));b.tick();state=decode(sent.get(timeout=1))
            self.assertEqual(state['type'],'engine_state')
            b._receive_bytes(encode(message('actuators',1,0,{'load_nm':33},source='ecu')))
            b._receive_bytes(encode(message('clock_sync',2,0,{'echo_sequence':state['sequence'],'ecu_time_us':100},source='ecu')))
            e.step();self.assertEqual(e.model.load_nm,33);self.assertEqual(b.metrics['ecu_offset_us'],100)
            self.assertIsNotNone(b.metrics['rtt_us'])
            b._receive_bytes(b'[]\n');self.assertEqual(b.decoder.errors,1)
        finally:b.close()
        self.assertFalse(b.worker.is_alive())

if __name__=='__main__':unittest.main()
