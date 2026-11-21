"""Linux CLI supervisor; --duration je wall time, čas motoru je ve výpisu."""

import argparse
import json
import logging
from pathlib import Path
from time import monotonic, sleep
from supervisor import Supervisor
from model import EngineConfig
from signals import SignalGenerator
from telemetry import format_sample, serialize_record


def main():
    parser = argparse.ArgumentParser(description="ECU SIL / Wokwi bridge")
    parser.add_argument("--mode", choices=["mock", "wokwi"], default="mock")
    parser.add_argument("--url", default="rfc2217://localhost:4000")
    parser.add_argument(
        "--wokwi-hardware",
        action="store_true",
        help="Isolated hardware chip profile with CRC32",
    )
    parser.add_argument("--hardware-mode", choices=["buffered", "free"], default="buffered")
    parser.add_argument("--lookahead-us", type=int, default=100000)
    parser.add_argument("--baudrate", type=int)
    parser.add_argument(
        "--duration", type=float, help="Wall seconds; CLI default 15, GUI until closed"
    )
    parser.add_argument("--gui", action="store_true", help="Live desktop visualization (Tk)")
    parser.add_argument("--vehicle", action="store_true", help="Enable whole-car teaching model and dashboard")
    parser.add_argument("--drive", action="store_true", help="Enable circuit driving (add --gui for view)")
    parser.add_argument("--joypad", default="/dev/input/js0", help="Linux joystick device")
    parser.add_argument("--joypad-config", type=Path, help="Joypad mapping JSON")
    parser.add_argument("--selector", choices=["P", "R", "N", "D"], default="N")
    parser.add_argument("--brake", type=float, default=0)
    parser.add_argument("--steer", type=float, default=0, help="Steering angle in degrees (-30..30)")
    parser.add_argument("--road-mu", type=float, default=0.85, help="Road friction (0.05..1.2)")
    parser.add_argument("--throttle", type=float, default=0.35)
    parser.add_argument("--rate", type=float, default=20)
    parser.add_argument("--step-us", type=int, default=1000)
    parser.add_argument("--speed", type=float, default=1, help="Simulation / wall time ratio (0,1]")
    parser.add_argument("--rpm", type=float, help="Fixed RPM test bench; omit for free dynamics")
    parser.add_argument("--load", type=float, default=12)
    parser.add_argument(
        "--config", type=Path, default=Path(__file__).with_name("engine_config.json")
    )
    parser.add_argument(
        "--signal-events",
        type=Path,
        help="Record generated host CKP/CMP edges as JSONL",
    )
    parser.add_argument("--telemetry", type=Path, help="Write JSON Lines telemetry")
    parser.add_argument(
        "--console-telemetry",
        action="store_true",
        help="Print telemetry also while GUI is open",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    if args.drive:
        args.vehicle = True
        if args.rpm is not None:
            parser.error("--drive nelze kombinovat se stolici --rpm")
    if args.wokwi_hardware and args.mode != "wokwi":
        parser.error("--wokwi-hardware requires --mode wokwi")
    if args.baudrate is not None and not 1 <= args.baudrate <= 2000000:
        parser.error("baudrate must be in 1..2000000")
    if args.baudrate is None:
        args.baudrate = 2000000 if args.wokwi_hardware else 115200
    import math

    if (
        not all(math.isfinite(x) and x > 0 for x in (args.rate, args.speed))
        or (args.duration is not None and (not math.isfinite(args.duration) or args.duration <= 0))
        or args.speed > 1
        or args.step_us <= 0
    ):
        parser.error("duration/rate/step must be positive; speed in (0,1]")
    try:
        settings = json.loads(args.config.read_text())
        app = Supervisor(
            args.mode,
            args.url,
            args.step_us / 1e6,
            args.speed,
            EngineConfig(**settings["engine"]),
            SignalGenerator(**settings["signals"]),
            args.baudrate,
            args.wokwi_hardware,
            args.hardware_mode,
            args.lookahead_us,
            vehicle=args.vehicle,
        )
        from joypad import Mapping
        app.joypad_mapping_manual = args.joypad_config is not None
        app.joypad_device = args.joypad
        app.joypad_mapping = Mapping.load(args.joypad_config) if args.joypad_config else Mapping()
        initial = {"throttle": args.throttle, "load_nm": args.load}
        if args.rpm is not None:
            initial["rpm"] = args.rpm
        # Validace před spuštěním vláken.
        app.configure_initial(initial)
        if args.vehicle:
            app.engine.vehicle.command({"selector": args.selector, "brake": args.brake,
                                        "steer_deg": args.steer, "mu_left": args.road_mu,
                                        "mu_right": args.road_mu})
        if args.drive:
            app.engine.enable_driving()
    except (ValueError, TypeError, KeyError, OSError, RuntimeError) as exc:
        parser.error(str(exc))
    output = args.telemetry.open("w", encoding="utf-8", buffering=1) if args.telemetry else None
    signals_output = (
        args.signal_events.open("w", encoding="utf-8", buffering=1) if args.signal_events else None
    )
    app.engine.collect_events = signals_output is not None
    wall_start = monotonic()

    def record(frame, diagnostics):
        wall_elapsed = monotonic() - wall_start
        if not args.gui or args.console_telemetry:
            print(format_sample(frame, diagnostics, wall_elapsed), flush=True)
        if output:
            output.write(serialize_record(frame, diagnostics, wall_elapsed) + "\n")
        if signals_output:
            for event in app.engine.drain_events(4096):
                signals_output.write(json.dumps(event, allow_nan=False) + "\n")

    try:
        app.start()
        if args.gui:
            try:
                from gui import run_gui

                run_gui(app, args.rate, record, args.duration)
            except ImportError as exc:
                parser.exit(1, f"GUI vyžaduje Tk: nainstalujte python3-tk. {exc}\n")
            except RuntimeError as exc:
                parser.exit(1, str(exc) + "\n")
            return
        duration = args.duration if args.duration is not None else 15
        start, deadline = monotonic(), monotonic()
        while monotonic() - start < duration:
            frame = app.bridge.tick()
            diagnostics = app.bridge.diagnostics()
            record(frame, diagnostics)
            deadline += 1 / args.rate
            sleep(max(0, min(deadline, start + duration) - monotonic()))
    except KeyboardInterrupt:
        pass
    finally:
        app.close()
        if output:
            output.close()
        if signals_output:
            signals_output.close()


if __name__ == "__main__":
    main()
