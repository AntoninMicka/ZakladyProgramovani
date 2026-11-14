"""Volitelné skutečné Tk widgety; bez přístupu k displeji se testy nespouštějí."""

import os
import unittest
from supervisor import Supervisor
from model import EngineConfig


@unittest.skipUnless(
    os.environ.get("ECU_TEST_GUI") == "1", "enable with ECU_TEST_GUI=1 and a display"
)
class GuiTests(unittest.TestCase):
    def test_controls_canvas_and_shutdown(self):
        import tkinter as tk
        from gui import EngineView

        root = tk.Tk()
        app = Supervisor()
        view = EngineView(root, app)
        try:
            root.update()
            self.assertTrue(view.canvas.find_all())
            view.throttle.set(70)
            view.load.set(30)
            view.command()
            app.engine.step()
            state = app.engine.snapshot()
            self.assertEqual(state["throttle"], 0.7)
            self.assertEqual(state["load_nm"], 30)
            view.toggle_pause()
            time = app.engine.clock.time_us
            app.engine.step()
            self.assertEqual(app.engine.clock.time_us, time)
            view.toggle_pause()
            app.engine.step()
            self.assertGreater(app.engine.clock.time_us, time)
            view.speed.set("0.02")
            view.change_speed()
            self.assertEqual(app.engine.speed, 0.02)
            view.draw(app.engine.snapshot(), {})
            self.assertTrue(
                any(
                    "EXPANZE" == view.canvas.itemcget(i, "text")
                    for i in view.canvas.find_all()
                    if view.canvas.type(i) == "text"
                )
            )
        finally:
            view.close()
            app.close()
        self.assertFalse(app.engine.is_alive())

    def test_sixteen_cylinders_render(self):
        import tkinter as tk
        from gui import EngineView

        root = tk.Tk()
        app = Supervisor(config=EngineConfig(cylinders=16))
        view = EngineView(root, app)
        try:
            root.update()
            labels = [
                view.canvas.itemcget(i, "text")
                for i in view.canvas.find_all()
                if view.canvas.type(i) == "text"
            ]
            self.assertIn("VÁLEC 16", labels)
        finally:
            view.close()
            app.close()

    def test_telemetry_panel_bounds_clear_and_export(self):
        import json
        import tempfile
        from pathlib import Path
        import tkinter as tk
        from gui import EngineView
        from telemetry import TelemetryBuffer

        root = tk.Tk()
        app = Supervisor()
        view = EngineView(root, app)
        try:
            root.update()
            view.notebook.select(1)
            view.clear_telemetry()
            view.telemetry = TelemetryBuffer(3)
            for _ in range(6):
                app.engine.step()
                view.next_telemetry_wall = 0
                view.update_telemetry(app.engine.snapshot(), dict(app.bridge.metrics))
            self.assertEqual(len(view.telemetry.samples), 3)
            self.assertEqual(view.log_rows, 3)
            text = view.telemetry_log.get("1.0", "end-1c")
            self.assertEqual(len(text.splitlines()), 3)
            self.assertIn("RPM=", text)
            self.assertIn("Poslední dwell", view.current_telemetry.get("1.0", "end"))
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "samples.jsonl"
                view.export_telemetry(path)
                records = [json.loads(line) for line in path.read_text().splitlines()]
                self.assertEqual(len(records), 3)
                self.assertIn("diagnostics", records[-1]["state"])
                txt = Path(directory) / "samples.txt"
                view.export_telemetry(txt)
                self.assertIn("RPM=", txt.read_text())
            view.clear_telemetry()
            self.assertFalse(view.telemetry.samples)
            self.assertEqual(view.telemetry_log.get("1.0", "end-1c"), "")
        finally:
            view.close()
            app.close()

    def test_wokwi_tab_cli_check_and_live_process(self):
        import json
        import sys
        import tempfile
        import time
        from pathlib import Path
        from threading import Event
        import tkinter as tk
        from gui import EngineView

        simulator = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="ecu-gui-wokwi-") as directory:
            project = Path(directory)
            (project / "config").mkdir()
            (project / "tests").mkdir()
            (project / "firmware/src").mkdir(parents=True)
            (project / "scripts").mkdir()
            source = project / "firmware/src/main.cpp"
            source.write_text("void loop() {}\n")
            (project / "scripts/build.py").write_text(
                "import sys\nfrom pathlib import Path\np=Path(__file__).resolve().parents[1]\ntext=(p/'firmware/src/main.cpp').read_text()\nif 'BUILD_ERROR' in text:\n print('main.cpp: error: invalid source',flush=True);raise SystemExit(1)\n(p/'firmware.bin').write_bytes(text.encode())\nprint('BUILD_OK',flush=True)\n"
            )
            (project / "config/engine.json").write_text(
                (simulator / "wokwi/hardware/config/engine.json").read_text()
            )
            (project / "firmware.bin").write_bytes(b"fixture")
            (project / "chip.wasm").write_bytes(b"\0asm")
            (project / "diagram.json").write_text("{}")
            (project / "wokwi.toml").write_text(
                "[wokwi]\nfirmware='firmware.bin'\n[[chip]]\nname='fixture'\nbinary='chip.wasm'\n"
            )
            (project / "tests/prototype.yaml").write_text("name: fixture\n")
            cli = project / "fake-wokwi"
            cli.write_text(
                "#!/usr/bin/python3\n"
                + "import sys\n"
                + f"sys.path.insert(0,{str(simulator)!r})\n"
                + "from protocol import decode,encode,message\n"
                "if '--version' in sys.argv:\n print('fake CLI version',flush=True);raise SystemExit(0)\n"
                "if '--interactive' not in sys.argv:\n print('fake scenario complete',flush=True);raise SystemExit(0)\n"
                "print('fake live ready',flush=True)\n"
                "sequence=0\n"
                "for line in sys.stdin:\n"
                " state=decode(line);sequence+=1\n"
                " data={'echo_sequence':state['sequence'],'ecu_time_us':state['simulation_time_us'],"
                "'hardware_session':state['data']['hardware']['session']}\n"
                " print(encode(message('clock_sync',sequence,state['simulation_time_us'],data,source='engine-interface'),integrity=True).decode(),end='',flush=True)\n"
            )
            cli.chmod(0o755)
            root = tk.Tk()
            app = Supervisor()
            app.start()
            view = EngineView(root, app)
            panel = view.wokwi_panel
            panel.cli.set(str(cli))
            panel.project.set(str(project))
            panel.token.set("wok_" + "T" * 40)

            def wait_for(condition):
                deadline = time.monotonic() + 4
                while time.monotonic() < deadline:
                    root.update()
                    if condition():
                        return
                    Event().wait(0.01)
                self.fail("GUI operation did not complete: " + panel.status.get())

            try:
                root.update()
                view.notebook.select(2)
                panel.check_cli()
                wait_for(lambda: panel.job is None and not panel.busy)
                self.assertIn("fake CLI version", panel.log.get("1.0", "end"))
                panel.mode.set("Živá smyčka motoru")
                panel.start()
                wait_for(
                    lambda: (
                        app.mode == "wokwi"
                        and app.bridge.metrics["received"] > 0
                        and not app.engine.snapshot()["paused"]
                    )
                )
                self.assertIn("hardware potvrdil", panel.status.get())
                self.assertEqual(panel.token.get(), "")
                # Samostatný editor kompiluje při běžícím starém procesu.
                from unittest.mock import patch
                from ecu_source import source_revision

                editor = view.ecu_editor
                editor.sync_project()
                old_pid = panel.runner.process.pid
                with patch("wokwi_gui.find_pio", return_value=sys.executable):
                    editor.code.delete("1.0", "end")
                    editor.code.insert("1.0", "BUILD_ERROR\n")
                    editor.build(True)
                    wait_for(lambda: panel.build_context is None and not panel.builder.busy)
                    self.assertIn("selhalo", panel.build_status)
                    self.assertEqual(panel.runner.process.pid, old_pid)
                    self.assertEqual(app.mode, "wokwi")
                    editor.code.delete("1.0", "end")
                    editor.code.insert("1.0", "void loop() { /* new revision */ }\n")
                    editor.build(True)
                    wait_for(
                        lambda: (
                            panel.running_revision == source_revision(project)
                            and panel.runner.process is not None
                            and panel.runner.process.pid != old_pid
                        )
                    )
                    self.assertIn("nov", panel.build_status.lower())
                    self.assertEqual((project / "firmware.bin").read_bytes(), source.read_bytes())
                panel.stop()
                wait_for(lambda: app.mode == "mock" and not panel.busy and not panel.runner.busy)
                self.assertTrue(app.engine.snapshot()["paused"])
                self.assertNotIn("wok_" + "T" * 40, panel.log.get("1.0", "end"))
                panel.mode.set("Prototyp (scénář)")
                panel.token.set("wok_" + "T" * 40)
                panel.start()
                wait_for(lambda: panel.job is None and not panel.busy and not panel.runner.busy)
                self.assertEqual(app.mode, "mock")
                self.assertIn("fake scenario complete", panel.log.get("1.0", "end"))
            finally:
                view.close()
                app.close()
            self.assertFalse(panel.runner.busy)

    def test_wokwi_missing_token_is_actionable(self):
        import tkinter as tk
        from unittest.mock import patch
        from pathlib import Path
        import sys
        from gui import EngineView

        root = tk.Tk()
        app = Supervisor()
        view = EngineView(root, app)
        try:
            with (
                patch.dict(os.environ, {}, clear=True),
                patch.object(
                    view.wokwi_panel,
                    "_paths",
                    return_value=(Path(sys.executable), Path.cwd()),
                ),
            ):
                view.wokwi_panel.start()
            self.assertIn("WOKWI_CLI_TOKEN", view.wokwi_panel.status.get())
            self.assertFalse(view.wokwi_panel.runner.busy)
        finally:
            view.close()
            app.close()
