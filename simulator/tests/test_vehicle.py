"""Ověření přenosu momentu, CAN, ABS/ESP a společného virtuálního času."""

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

from bridge import MockBridge
from can_bus import CanBus, Frame, decode, encode
from engine import Engine
from vehicle import VehicleConfig, VehicleModel, dashboard


class CanTests(unittest.TestCase):
    def test_frame_validation_and_payload_roundtrip(self):
        for identifier, payload in ((2048, b""), (-1, b""), (1, b"012345678")):
            with self.assertRaises(ValueError):
                Frame(identifier, payload, "test", 0)
        values = {"rpm": 1234, "fuel_us": 2500, "torque_nm": -12, "pedal_permille": 500}
        self.assertEqual(decode(0x100, encode(0x100, **values)), values)

    def test_arbitration_latency_and_no_preemption(self):
        bus = CanBus()
        bus.send(0x300, b"a", "low", 0)
        bus.send(0x100, b"b", "high", 0)
        bus.advance(1)
        self.assertEqual(bus.delivered, 0)
        bus.send(0x010, b"c", "later", 1)
        bus.advance(1000)
        self.assertEqual([f.identifier for f in bus.history], [0x100, 0x010, 0x300])
        self.assertGreater(bus.history[0].time_us, 1)
        self.assertEqual(bus.delivered, 3)

    def test_capacity_disconnect_timeout_and_recovery(self):
        bus = CanBus(capacity=1, history=2)
        payload = encode(0x200, gear=2, shifting=0)
        self.assertTrue(bus.send(0x200, payload, "TCU", 0))
        self.assertFalse(bus.send(0x200, payload, "TCU", 0))
        bus.advance(1000)
        self.assertEqual(bus.read(0x200, 1000)["gear"], 2)
        self.assertIsNone(bus.read(0x200, 400000))
        bus.enabled = False
        self.assertFalse(bus.send(0x200, payload, "TCU", 1000))
        bus.advance(400000)
        self.assertEqual(bus.snapshot()["queue_depth"], 0)
        self.assertTrue(dashboard(bus, 400000)["can_fault"])
        bus.enabled = True
        for t in (400000, 401000, 402000):
            bus.send(0x200, payload, "TCU", t)
            bus.advance(t + 1000)
        self.assertEqual(len(bus.history), 2)
        with self.assertRaises(ValueError):
            bus.advance(1)


class VehicleTests(unittest.TestCase):
    def advance(self, vehicle, seconds, rpm=1800, torque=60):
        for _ in range(round(seconds * 1000)):
            vehicle.step(0.001, rpm, torque, 0.4, 1500)

    def moving(self, speed=20):
        v = VehicleModel()
        v.speed = speed
        v.wheel_omega = [speed / v.config.wheel_radius_m] * 4
        return v

    def test_commands_are_atomic_and_finite(self):
        v = VehicleModel()
        for command in (
            {"brake": 0.5, "mu_left": float("nan")},
            {"selector": "X"},
            {"abs_enabled": 1},
            {"brake": -1},
            {"unknown": 0},
        ):
            with self.assertRaises(ValueError):
                v.command(command)
            self.assertEqual(v.brake, 0)
        with self.assertRaises(ValueError):
            VehicleConfig(mass_kg=-1)

    def test_neutral_and_open_differential_with_split_friction(self):
        neutral = VehicleModel()
        self.advance(neutral, 0.5)
        self.assertAlmostEqual(neutral.speed, 0)
        self.assertEqual(neutral.engine_load_nm, 0)
        v = VehicleModel()
        v.command({"selector": "D", "mu_left": 0.08, "mu_right": 0.9})
        self.advance(v, 2)
        self.assertGreater(v.speed, 0)
        self.assertEqual(v.drive_torque[0], v.drive_torque[1])
        self.assertGreater(v.wheel_omega[0], v.wheel_omega[1])
        self.assertGreater(v.engine_load_nm, 0)

    def test_tcu_shift_hysteresis_and_reverse_interlock(self):
        v = VehicleModel()
        v.command({"selector": "D"})
        self.advance(v, 0.5, rpm=1800)
        self.assertEqual(v.gear, 1)
        self.advance(v, 0.6, rpm=3000)
        self.assertEqual(v.gear, 2)
        self.assertEqual(v.tcu.gear, 2)
        v.speed = 10
        v.command({"selector": "R"})
        self.advance(v, 0.25)
        self.assertEqual(v.gear, 0)
        v.speed = 0
        v.wheel_omega = [0] * 4
        self.advance(v, 0.5)
        self.assertEqual(v.gear, -1)
        self.assertLess(v.speed, 0)

    def test_abs_releases_locked_wheels_on_ice(self):
        locked, regulated = self.moving(), self.moving()
        for v, enabled in ((locked, False), (regulated, True)):
            v.command({"brake": 1, "mu_left": 0.15, "mu_right": 0.15, "abs_enabled": enabled})
            self.advance(v, 1)
            self.assertLess(v.speed, 20)
        self.assertEqual(locked.wheel_omega, [0] * 4)
        self.assertTrue(regulated.abs_active)
        self.assertTrue(all(w > 0 for w in regulated.wheel_omega))
        self.assertTrue(all(p < 1 for p in regulated.brake_pressure))

    def test_esp_uses_yaw_error_and_selective_braking(self):
        disabled, enabled = self.moving(22), self.moving(22)
        for v, switch in ((disabled, False), (enabled, True)):
            v.command({"steer_deg": 20, "mu_left": 0.2, "mu_right": 0.2, "esp_enabled": switch})
            self.advance(v, 0.5)
        self.assertFalse(disabled.esp_active)
        self.assertEqual(disabled.torque_factor, 1)
        self.assertTrue(enabled.esp_active)
        self.assertLess(enabled.torque_factor, 1)
        self.assertGreater(enabled.brake_pressure[2], enabled.brake_pressure[3])
        self.assertGreater(enabled.yaw_rate, disabled.yaw_rate)

    def test_dashboard_reads_only_delivered_can_and_can_failure_falls_back(self):
        v = self.moving()
        self.assertIsNone(v.snapshot()["dashboard"]["rpm"])
        self.advance(v, 0.1, rpm=2200)
        self.assertEqual(v.snapshot()["dashboard"]["rpm"], 2200)
        self.assertFalse(v.snapshot()["dashboard"]["can_fault"])
        v.command({"can_enabled": False, "brake": 0.5})
        self.advance(v, 0.4)
        self.assertTrue(v.snapshot()["dashboard"]["can_fault"])
        self.assertIsNone(v.snapshot()["dashboard"]["rpm"])
        self.assertEqual(v.gear, 0)
        self.assertEqual(v.brake_pressure, [0.5] * 4)
        v.command({"can_enabled": True})
        self.advance(v, 0.1)
        self.assertFalse(v.snapshot()["dashboard"]["can_fault"])

    def test_sensors_and_json_are_finite(self):
        v = VehicleModel()
        self.advance(v, 0.1)
        json.dumps(v.snapshot(), allow_nan=False)
        sensors = v.sensors()
        self.assertEqual(set(sensors["wheel_speed_kmh"]), {"FL", "FR", "RL", "RR"})
        self.assertGreater(sensors["oil_pressure_kpa"], 0)
        self.assertGreater(sensors["battery_v"], 12)
        self.assertGreater(sensors["fuel_level_l"], 0)
        self.assertEqual(sensors["barometric_pressure_kpa"], 101.3)


class VehicleEngineTests(unittest.TestCase):
    def test_clock_pause_reset_and_disable_remove_load(self):
        engine = Engine(vehicle=True)
        engine.vehicle_command({"selector": "D"})
        for _ in range(500):
            engine.step()
        self.assertEqual(engine.vehicle.time_us, engine.clock.time_us)
        before = engine.snapshot()
        engine.pause()
        for _ in range(100):
            engine.step()
        self.assertEqual(engine.snapshot(), before | {"paused": True})
        engine.resume()
        engine.reset()
        self.assertEqual(engine.vehicle.time_us, 0)
        self.assertEqual(engine.vehicle.speed, 0)
        self.assertEqual(engine.vehicle.selector, "N")
        engine.step()
        engine.set_vehicle_enabled(False)
        self.assertNotIn("vehicle", engine.snapshot())
        self.assertEqual(engine.model.drivetrain_load_nm, 0)
        self.assertEqual(engine.model.torque_factor, 1)
        engine.set_vehicle_enabled(True)
        engine.step()
        self.assertEqual(engine.vehicle.time_us, engine.clock.time_us)

    def test_actual_cpp_ecu_drives_vehicle_and_time_is_not_double_integrated(self):
        engine = Engine(vehicle=True)
        engine.vehicle.command({"selector": "D"})
        bridge = MockBridge(engine)
        try:
            bridge.start()
            for _ in range(3000):
                engine.step()
            s = engine.snapshot()
            self.assertGreater(s["vehicle"]["speed_kmh"], 1)
            self.assertGreater(s["vehicle"]["can"]["delivered"], 100)
            self.assertEqual(engine.vehicle.time_us, 3_000_000)
            self.assertEqual(s["diagnostics"]["rejected_commands"], 0)
            self.assertTrue(bridge.diagnostics()["controller"]["synced"])
            self.assertGreater(s["vehicle"]["gear"], 0)
        finally:
            bridge.close()

    def test_uart_does_not_carry_local_can_history(self):
        from unittest.mock import patch

        from bridge import RFC2217Bridge
        from protocol import MAX_FRAME

        engine = Engine(vehicle=True)
        for _ in range(200):
            engine.step()
        bridge = RFC2217Bridge(engine, "rfc2217://localhost:4000")
        with patch.object(bridge.worker, "send", return_value=True) as send:
            state = bridge.tick()
        self.assertIn("vehicle", state)
        raw = send.call_args.args[0]
        self.assertLess(len(raw), MAX_FRAME)
        self.assertNotIn("vehicle", json.loads(raw)["data"])

    def test_snapshot_does_not_leak_mutable_can_or_sensor_data(self):
        engine = Engine(vehicle=True)
        for _ in range(100):
            engine.step()
        old = engine.snapshot()
        old["vehicle"]["sensors"]["wheel_speed_kmh"]["FL"] = 99999
        old["vehicle"]["can"]["frames"].clear()
        current = engine.snapshot()
        self.assertNotEqual(current["vehicle"]["sensors"]["wheel_speed_kmh"]["FL"], 99999)
        self.assertTrue(current["vehicle"]["can"]["frames"])

    def test_vehicle_does_not_advance_without_engine_time(self):
        engine = Engine(vehicle=True)
        for _ in range(10):
            engine.snapshot()
        self.assertEqual(engine.vehicle.time_us, 0)

    def test_cli_car_mode_exports_nested_telemetry(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "car.jsonl"
            result = subprocess.run(
                [
                    sys.executable,
                    str(Path(__file__).resolve().parents[1] / "main.py"),
                    "--vehicle",
                    "--selector",
                    "D",
                    "--duration",
                    ".15",
                    "--telemetry",
                    str(path),
                ],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            rows = [json.loads(r) for r in path.read_text().splitlines()]
            self.assertIn("vehicle", rows[-1]["state"])
            self.assertIn("CAR=", result.stdout)


@unittest.skipUnless(os.environ.get("ECU_TEST_GUI") == "1", "requires Tk display")
class VehicleGuiTests(unittest.TestCase):
    def test_dashboard_controls_and_can_monitor(self):
        import tkinter as tk

        from gui import EngineView
        from supervisor import Supervisor

        root = tk.Tk()
        app = Supervisor(vehicle=True)
        view = EngineView(root, app)
        try:
            root.update()
            panel = view.vehicle_panel
            panel.selector.set("D")
            panel.brake.set(20)
            panel.command()
            for _ in range(100):
                app.engine.step()
            panel.refresh(app.engine.snapshot())
            self.assertEqual(app.engine.vehicle.selector, "D")
            self.assertEqual(app.engine.vehicle.brake, 0.2)
            self.assertTrue(panel.canvas.find_all())
            self.assertTrue(panel.frames.get_children())
            self.assertTrue(panel.sensors.get_children())
            panel.enabled.set(False)
            panel.toggle()
            panel.refresh(app.engine.snapshot())
            self.assertIsNone(app.engine.vehicle)
        finally:
            view.close()
            app.close()
