"""Životní cyklus aplikace, bez fyzikálních výpočtů."""
from engine import Engine
from bridge import MockBridge, RFC2217Bridge
from model import EngineConfig

class Supervisor:
    def __init__(self, mode='mock', url='rfc2217://localhost:4000', dt=.001, speed=1,
                 config=EngineConfig(), signals=None, baudrate=115200, hardware=False, hardware_mode='buffered', lookahead_us=100000):
        self.mode, self.url, self.baudrate = mode, url, baudrate
        self.hardware_options = dict(hardware=hardware, hardware_mode=hardware_mode, lookahead_us=lookahead_us)
        self.engine = Engine(dt=dt,speed=speed,config=config,signals=signals)
        self.bridge = MockBridge(self.engine) if mode == 'mock' else RFC2217Bridge(self.engine,url,baudrate,**self.hardware_options)

    def start(self):
        self.engine.start()
        try: self.bridge.start()
        except Exception:
            self.engine.stop()
            self.engine.join()
            raise

    def pause(self): self.engine.pause()
    def resume(self): self.engine.resume()
    def restart(self):
        # Nový běh má nový transport/session; staré zprávy se nesmí dostat do nového času.
        self.bridge.close()
        self.engine.pause()
        self.engine.reset()
        if isinstance(self.bridge,RFC2217Bridge):
            self.bridge = RFC2217Bridge(self.engine,self.url,self.baudrate,**self.hardware_options)
        else: self.bridge = MockBridge(self.engine)
        self.bridge.start()
        self.engine.resume()

    def close(self):
        self.engine.stop()
        try: self.bridge.close()
        finally:
            if self.engine.ident is not None: self.engine.join(timeout=2)
            if self.engine.is_alive(): raise RuntimeError('engine failed to stop')
