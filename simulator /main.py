"""Linux CLI supervisor; --duration je wall time, čas motoru je ve výpisu."""
import argparse
import json
import logging
from pathlib import Path
from time import monotonic, sleep
from supervisor import Supervisor
from model import EngineConfig
from signals import SignalGenerator
from telemetry import format_sample


def main():
    parser = argparse.ArgumentParser(description='ECU SIL / Wokwi bridge')
    parser.add_argument('--mode',choices=['mock','wokwi'],default='mock')
    parser.add_argument('--url',default='rfc2217://localhost:4000')
    parser.add_argument('--baudrate',type=int,default=115200)
    parser.add_argument('--duration',type=float,help='Wall seconds; CLI default 15, GUI until closed')
    parser.add_argument('--gui',action='store_true',help='Live desktop visualization (Tk)')
    parser.add_argument('--throttle',type=float,default=.35)
    parser.add_argument('--rate',type=float,default=20)
    parser.add_argument('--step-us',type=int,default=1000)
    parser.add_argument('--speed',type=float,default=1,help='Simulation / wall time ratio (0,1]')
    parser.add_argument('--rpm',type=float,help='Fixed RPM test bench; omit for free dynamics')
    parser.add_argument('--load',type=float,default=12)
    parser.add_argument('--config',type=Path,default=Path(__file__).with_name('engine_config.json'))
    parser.add_argument('--telemetry',type=Path,help='Write JSON Lines telemetry')
    parser.add_argument('--console-telemetry',action='store_true',help='Print telemetry also while GUI is open')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    import math
    if (not all(math.isfinite(x) and x>0 for x in (args.rate,args.speed))
            or (args.duration is not None and (not math.isfinite(args.duration) or args.duration<=0))
            or args.speed>1 or args.step_us<=0):
        parser.error('duration/rate/step must be positive; speed in (0,1]')
    try:
        settings = json.loads(args.config.read_text())
        app = Supervisor(args.mode,args.url,args.step_us/1e6,args.speed,
                         EngineConfig(**settings['engine']),SignalGenerator(**settings['signals']),args.baudrate)
        initial = {'throttle':args.throttle,'load_nm':args.load}
        if args.rpm is not None: initial['rpm'] = args.rpm
        # Validace před spuštěním vláken.
        app.engine.model.command(initial)
    except (ValueError,TypeError,KeyError,OSError) as exc:
        parser.error(str(exc))
    output = args.telemetry.open('w',encoding='utf-8',buffering=1) if args.telemetry else None
    wall_start = monotonic()
    def record(frame, diagnostics):
        wall_elapsed = monotonic()-wall_start
        if not args.gui or args.console_telemetry:
            print(format_sample(frame,diagnostics,wall_elapsed),flush=True)
        if output:
            output.write(json.dumps({'wall_elapsed_s':wall_elapsed,
                                     'state':frame,'bridge':diagnostics})+'\n')

    try:
        app.start()
        if args.gui:
            try:
                from gui import run_gui
                run_gui(app,args.rate,record,args.duration)
            except ImportError as exc:
                parser.exit(1,f'GUI vyžaduje Tk: nainstalujte python3-tk. {exc}\n')
            except RuntimeError as exc:
                parser.exit(1,str(exc)+'\n')
            return
        duration = args.duration if args.duration is not None else 15
        start, deadline = monotonic(), monotonic()
        while monotonic()-start < duration:
            frame = app.bridge.tick()
            diagnostics = app.bridge.diagnostics() if hasattr(app.bridge,'diagnostics') else app.bridge.metrics
            record(frame,diagnostics)
            deadline += 1/args.rate
            sleep(max(0,min(deadline,start+duration)-monotonic()))
    except KeyboardInterrupt:
        pass
    finally:
        app.close()
        if output: output.close()

if __name__ == '__main__': main()
