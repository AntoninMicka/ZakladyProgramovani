"""Pedál je vstup ECU; fyzikální model dostává palivo nezávisle na pedálu."""

from pathlib import Path
import shutil
import tempfile
import unittest
from bridge import MockBridge
from engine import Engine
from model import EngineModel
from native_ecu import NativeEcu, PROJECT


class PedalControlTests(unittest.TestCase):
    def test_physics_does_not_apply_pedal_a_second_time(self):
        a, b = EngineModel(), EngineModel()
        a.command({"throttle": 0, "injector_ms": 1.5})
        b.command({"throttle": 1, "injector_ms": 1.5})
        for _ in range(100):
            a.step(0.001)
            b.step(0.001)
        self.assertEqual(a.rpm, b.rpm)
        self.assertEqual(a.angle, b.angle)

    def test_linear_ecu_mapping_preserves_former_steady_torque(self):
        from model import REFERENCE_TORQUE_NM, FRICTION_BASE_NM, FRICTION_PER_RPM
        import math

        for pedal in (0, 0.2, 0.35, 0.5, 1):
            model = EngineModel()
            model.command({"throttle": pedal, "injector_ms": 3 * pedal, "ignition_deg": 15})
            before = model.rpm
            old_torque = REFERENCE_TORQUE_NM * pedal
            expected = (
                before
                + (old_torque - model.load_nm - FRICTION_BASE_NM - FRICTION_PER_RPM * before)
                / model.config.inertia
                * 60
                / (2 * math.pi)
                * 0.001
            )
            model.step(0.001)
            self.assertAlmostEqual(model.rpm, expected)

    def test_pedal_reaches_shared_ecu_and_changes_actual_pulses(self):
        for pedal, width in ((0, 0), (0.35, 1050), (0.5, 1500), (1, 3000)):
            engine = Engine()
            engine.model.command({"rpm": 1000, "throttle": pedal})
            bridge = MockBridge(engine)
            bridge.start()
            try:
                for _ in range(1000):
                    engine.step()
                self.assertEqual(engine.model.last_injection_us, dict.fromkeys(range(4), width))
                self.assertEqual(bridge.diagnostics()["controller"]["injection_us"], width)
                self.assertEqual(engine.diagnostics["rejected_commands"], 0)
            finally:
                bridge.close()

    def test_student_can_ignore_pedal_in_cpp_without_modifying_python(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            (project / "firmware/include").mkdir(parents=True)
            (project / "config").mkdir()
            shutil.copy(PROJECT / "config/engine.json", project / "config/engine.json")
            source = (PROJECT / "firmware/include/ecu_controller.h").read_text()
            (project / "firmware/include/ecu_controller.h").write_text(
                source.replace("ECU_INJECTION_US * accelerator", "ECU_INJECTION_US * 0.5")
            )
            results = []
            for pedal in (0.1, 0.9):
                engine = Engine()
                engine.model.command({"throttle": pedal})
                bridge = MockBridge(engine, NativeEcu(engine.config, engine.signals, project))
                bridge.start()
                try:
                    for _ in range(1000):
                        engine.step()
                    self.assertIsNone(engine.model.target_rpm)
                    self.assertEqual(set(engine.model.last_injection_us.values()), {1500})
                    results.append(engine.model.rpm)
                finally:
                    bridge.close()
            self.assertEqual(*results)
