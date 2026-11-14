"""Skutečné lokální TCP/RFC2217; opt-in kvůli síťovému sandboxu."""
import os
import queue
import socket
import threading
import time
import unittest
from bridge import RFC2217Bridge
from engine import Engine
from protocol import LineDecoder,encode,message

@unittest.skipUnless(os.environ.get('ECU_TEST_TCP')=='1','enable with ECU_TEST_TCP=1')
class RFC2217TCPTest(unittest.TestCase):
    def test_real_negotiation_reconnect(self):
        import serial
        from serial.rfc2217 import PortManager
        listener=socket.socket();listener.bind(('127.0.0.1',0));listener.listen(2);listener.settimeout(.1)
        stop=threading.Event();observed=queue.Queue();errors=queue.Queue()
        class Connection:
            def __init__(self,sock):self.sock=sock
            def write(self,data):self.sock.sendall(data)
        def server():
            session=0
            try:
                while not stop.is_set():
                    try:conn,_=listener.accept()
                    except socket.timeout:continue
                    session+=1
                    with conn,serial.serial_for_url('loop://') as port:
                        conn.settimeout(.1);manager=PortManager(port,Connection(conn));decoder=LineDecoder()
                        while not stop.is_set():
                            try:raw=conn.recv(4096)
                            except socket.timeout:continue
                            if not raw:break
                            frames=decoder.feed(b''.join(manager.filter(raw)))
                            for frame in frames:
                                if frame['type']=='engine_state':
                                    response=encode(message('actuators',session,0,{'load_nm':20+session},source='test-ecu'))
                                    conn.sendall(b''.join(manager.escape(response)));observed.put(session)
                            if frames and session==1:break
            except Exception as exc:
                if not stop.is_set():errors.put(exc)
        thread=threading.Thread(target=server,name='test-rfc2217-server');thread.start()
        e=Engine();b=RFC2217Bridge(e,f'rfc2217://127.0.0.1:{listener.getsockname()[1]}',retry=.01);b.start()
        try:
            self.assertTrue(b.worker.connected.wait(3));b.tick();self.assertEqual(observed.get(timeout=3),1)
            deadline=time.monotonic()+5
            while b.worker.generation<2 and time.monotonic()<deadline:stop.wait(.005)
            self.assertGreaterEqual(b.worker.generation,2);self.assertTrue(b.worker.connected.wait(3))
            baseline=b.metrics['received'];b.tick();self.assertEqual(observed.get(timeout=3),2)
            deadline=time.monotonic()+2
            while b.metrics['received']==baseline and time.monotonic()<deadline:stop.wait(.005)
            e.step();self.assertEqual(e.model.load_nm,22)
            self.assertTrue(errors.empty(),list(errors.queue))
        finally:
            b.close();stop.set();thread.join(2);listener.close()
        self.assertFalse(thread.is_alive());self.assertFalse(b.worker.is_alive())

if __name__=='__main__':unittest.main()
