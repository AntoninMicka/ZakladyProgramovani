"""Volitelné skutečné Tk widgety; bez přístupu k displeji se testy nespouštějí."""
import os
import unittest
from supervisor import Supervisor
from model import EngineConfig

@unittest.skipUnless(os.environ.get('ECU_TEST_GUI')=='1','enable with ECU_TEST_GUI=1 and a display')
class GuiTests(unittest.TestCase):
    def test_controls_canvas_and_shutdown(self):
        import tkinter as tk
        from gui import EngineView
        root=tk.Tk()
        app=Supervisor()
        view=EngineView(root,app)
        try:
            root.update()
            self.assertTrue(view.canvas.find_all())
            view.throttle.set(70);view.load.set(30);view.command()
            app.engine.step()
            state=app.engine.snapshot()
            self.assertEqual(state['throttle'],.7)
            self.assertEqual(state['load_nm'],30)
            view.toggle_pause();time=app.engine.clock.time_us
            app.engine.step();self.assertEqual(app.engine.clock.time_us,time)
            view.toggle_pause();app.engine.step();self.assertGreater(app.engine.clock.time_us,time)
            view.speed.set('0.02');view.change_speed();self.assertEqual(app.engine.speed,.02)
            view.draw(app.engine.snapshot(),{})
            self.assertTrue(any('EXPANZE'==view.canvas.itemcget(i,'text')
                                for i in view.canvas.find_all() if view.canvas.type(i)=='text'))
        finally:
            view.close();app.close()
        self.assertFalse(app.engine.is_alive())

    def test_sixteen_cylinders_render(self):
        import tkinter as tk
        from gui import EngineView
        root=tk.Tk();app=Supervisor(config=EngineConfig(cylinders=16))
        view=EngineView(root,app)
        try:
            root.update()
            labels=[view.canvas.itemcget(i,'text') for i in view.canvas.find_all()
                    if view.canvas.type(i)=='text']
            self.assertIn('VÁLEC 16',labels)
        finally:view.close();app.close()

    def test_telemetry_panel_bounds_clear_and_export(self):
        import json
        import tempfile
        from pathlib import Path
        import tkinter as tk
        from gui import EngineView
        from telemetry import TelemetryBuffer
        root=tk.Tk();app=Supervisor();view=EngineView(root,app)
        try:
            root.update()
            view.notebook.select(1)
            view.clear_telemetry()
            view.telemetry=TelemetryBuffer(3)
            for _ in range(6):
                app.engine.step()
                view.next_telemetry_wall=0
                view.update_telemetry(app.engine.snapshot(),dict(app.bridge.metrics))
            self.assertEqual(len(view.telemetry.samples),3)
            self.assertEqual(view.log_rows,3)
            text=view.telemetry_log.get('1.0','end-1c')
            self.assertEqual(len(text.splitlines()),3)
            self.assertIn('RPM=',text)
            self.assertIn('Poslední dwell',view.current_telemetry.get('1.0','end'))
            with tempfile.TemporaryDirectory() as directory:
                path=Path(directory)/'samples.jsonl'
                view.export_telemetry(path)
                records=[json.loads(line) for line in path.read_text().splitlines()]
                self.assertEqual(len(records),3)
                self.assertIn('diagnostics',records[-1]['state'])
                txt=Path(directory)/'samples.txt';view.export_telemetry(txt)
                self.assertIn('RPM=',txt.read_text())
            view.clear_telemetry()
            self.assertFalse(view.telemetry.samples)
            self.assertEqual(view.telemetry_log.get('1.0','end-1c'),'')
        finally:view.close();app.close()
