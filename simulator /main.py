import argparse
import logging
from time import monotonic, sleep
from engine import Engine
from bridge import MockBridge, RFC2217Bridge


def main():
    parser = argparse.ArgumentParser(description='Engine SIL / Wokwi bridge')
    parser.add_argument('--mode', choices=['mock', 'wokwi'], default='mock')
    parser.add_argument('--url', default='rfc2217://localhost:4000')
    parser.add_argument('--duration', type=float, default=15.0)
    parser.add_argument('--throttle', type=float, default=0.35)
    parser.add_argument('--rate', type=float, default=20.0, help='Sensor frames per second')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    if args.rate <= 0 or args.duration <= 0:
        parser.error('rate and duration must be positive')
    engine = Engine()
    engine.command({'throttle': args.throttle})
    bridge = None
    try:
        bridge = MockBridge(engine) if args.mode == 'mock' else RFC2217Bridge(engine, args.url)
        engine.start()
        if isinstance(bridge, RFC2217Bridge):
            bridge.start()
        start = monotonic()
        next_tick = start
        while monotonic() - start < args.duration:
            frame = bridge.tick()
            print(f"t={frame['time_s']:6.2f}s RPM={frame['rpm']:7.1f} "
                  f"MAP={frame['map_kpa']:5.1f}kPa lambda={frame['lambda_value']:.2f}")
            next_tick += 1.0 / args.rate
            sleep(max(0.0, next_tick - monotonic()))
    except KeyboardInterrupt:
        pass
    finally:
        engine.stop()
        if bridge is not None and hasattr(bridge, 'close'):
            bridge.close()
        if engine.ident is not None:
            engine.join(timeout=1)


if __name__ == '__main__':
    main()
