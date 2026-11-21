"""Reprodukovatelná jízda s reálnou lokální C++ ECU, bez GUI a bez čekání na čas."""

import argparse
import json
from pathlib import Path

from bridge import MockBridge
from engine import Engine


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Volitelný JSONL záznam")
    args = parser.parse_args()
    engine = Engine(vehicle=True)
    bridge = MockBridge(engine)
    output = args.output.open("w", encoding="utf-8") if args.output else None
    try:
        bridge.start()
        scenarios = [
            ("Rozjezd D, plyn 70 %", 6, {"throttle": 0.7}, {"selector": "D"}),
            ("Zatáčka na kluzku", 2, {}, {"mu_left": 0.2, "mu_right": 0.2, "steer_deg": 20}),
            ("Brzdění na kluzku", 3, {"throttle": 0}, {"steer_deg": 0, "brake": 1}),
            ("Výpadek CAN", 1, {}, {"can_enabled": False}),
            ("Obnova CAN, neutrál", 1, {}, {"can_enabled": True, "selector": "N", "brake": 0}),
        ]
        for label, seconds, motor, car in scenarios:
            engine.command(motor)
            engine.vehicle_command(car)
            for step in range(seconds * 1000):
                engine.step()
                if step % 200 == 199:
                    state = engine.snapshot()
                    if output:
                        output.write(
                            json.dumps(
                                {"scenario": label, "state": state},
                                ensure_ascii=False,
                                allow_nan=False,
                            )
                            + "\n"
                        )
            state = engine.snapshot()
            v = state["vehicle"]
            print(
                f"{label}: t={state['time_s']:.1f}s, {v['speed_kmh']:.1f} km/h, "
                f"{state['rpm']:.0f} rpm, stupeň={v['gear']}, ABS={v['abs_active']}, "
                f"ESP={v['esp_active']}, CAN chyba={v['dashboard']['can_fault']}"
            )
    finally:
        bridge.close()
        if output:
            output.close()


if __name__ == "__main__":
    main()
