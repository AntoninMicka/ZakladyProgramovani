"""Mock vykonává C++ firmware: pulzy, watchdog, záměna zdroje a nezávislost na GUI."""

import json
from pathlib import Path
import shutil
import tempfile
import unittest

from bridge import MockBridge
from engine import Engine
from native_ecu import NativeEcu, PROJECT
from signals import SignalGenerator
from supervisor import Supervisor


class NativeEcuTests(unittest.TestCase):
    def run_engine(self, rate=20, step_us=1000, speed=1):
        engine = Engine(dt=step_us / 1e6, speed=speed)
        engine.model.command({"rpm": 1000})
        bridge = MockBridge(engine)
        bridge.start()
        for _ in range(2000000 // step_us):
            if engine.clock.time_us % (1000000 // rate) == 0:
                bridge.tick()
            engine.step()
        return engine, bridge

    def test_same_controller_generates_all_channels_and_measured_widths(self):
        engine, bridge = self.run_engine()
        try:
            state = engine.snapshot()
            self.assertEqual(state["last_injection_us"], dict.fromkeys(range(4), 3000))
            self.assertEqual(state["last_dwell_us"], dict.fromkeys(range(4), 2000))
            self.assertAlmostEqual(state["ignition_deg"], 15, delta=0.4)
            self.assertEqual(state["diagnostics"]["rejected_commands"], 0)
            self.assertEqual(state["diagnostics"]["late_events"], 0)
            ecu = bridge.diagnostics()["controller"]
            self.assertTrue(ecu["synced"])
            self.assertAlmostEqual(ecu["rpm"], 1000, delta=2)
            self.assertEqual(ecu["errors"], 0)
            self.assertGreater(ecu["events"], 200)
        finally:
            bridge.close()

    def test_virtual_outputs_independent_of_ui_rate_and_wall_speed(self):
        states = []
        for rate, speed in ((2, 1), (100, 0.02)):
            engine, bridge = self.run_engine(rate=rate, speed=speed)
            states.append(
                (engine.snapshot()["last_injection_us"], bridge.diagnostics()["controller"])
            )
            bridge.close()
        self.assertEqual(*states)

    def test_pause_reset_and_stop_watchdog(self):
        engine, bridge = self.run_engine()
        try:
            engine.pause()
            before = bridge.diagnostics()["controller"]
            engine.step()
            self.assertEqual(bridge.diagnostics()["controller"], before)
            engine.resume()
            # Bez dalšího pohybu se zastaví příchod CKP hran.
            engine.model.command({"rpm": 0})
            for _ in range(30):
                engine.step()
            self.assertFalse(bridge.diagnostics()["controller"]["synced"])
            self.assertFalse(engine.model.open_injectors)
            self.assertFalse(engine.model.charging)
            engine.reset()
            self.assertEqual(bridge.diagnostics()["controller"]["events"], 0)
        finally:
            bridge.close()

    def test_changed_cpp_source_changes_mock_and_failed_build_preserves_running(self):
        app = Supervisor()
        app.configure_initial({"rpm": 1000})
        app.bridge.start()
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            (project / "firmware/include").mkdir(parents=True)
            (project / "config").mkdir()
            header = project / "firmware/include/ecu_controller.h"
            shutil.copy(PROJECT / "config/engine.json", project / "config/engine.json")
            original = (PROJECT / "firmware/include/ecu_controller.h").read_text()
            header.write_text(
                original.replace("now + ECU_INJECTION_US", "now + ECU_INJECTION_US + 1000")
            )
            replacement = NativeEcu(app.engine.config, app.engine.signals, project)
            before = app.bridge.controller.revision
            app.apply_mock_ecu(replacement)
            for _ in range(1000):
                app.engine.step()
            self.assertNotEqual(app.bridge.controller.revision, before)
            self.assertEqual(set(app.engine.model.last_injection_us.values()), {4000})
            live = app.bridge.controller
            header.write_text("this is invalid C++")
            with self.assertRaisesRegex(RuntimeError, "Překlad Mock ECU selhal"):
                NativeEcu(app.engine.config, app.engine.signals, project)
            self.assertIs(app.bridge.controller, live)
            app.engine.step()
        app.close()

    def test_geometry_and_cylinder_count_are_native_configuration(self):
        from model import EngineConfig

        engine = Engine(
            config=EngineConfig(cylinders=2), signals=SignalGenerator(teeth=36, missing=1)
        )
        engine.model.command({"rpm": 1000})
        bridge = MockBridge(engine)
        bridge.start()
        try:
            for _ in range(1000):
                engine.step()
            self.assertEqual(engine.model.last_injection_us, {0: 3000, 1: 3000})
            self.assertTrue(bridge.diagnostics()["controller"]["synced"])
        finally:
            bridge.close()
