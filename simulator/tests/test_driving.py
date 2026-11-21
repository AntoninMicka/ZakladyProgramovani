"""Okruh a skutečná vazba na ECU; vstup joypadu přes syntetické joydev události."""

import json
import math
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from bridge import MockBridge
from engine import Engine
from joypad import EVENT, Joypad, Mapping, controls
from racetrack import Circuit, DrivingSession, LapTimer


class TrackTests(unittest.TestCase):
    def test_closed_track_projection_and_distance(self):
        track = Circuit()
        self.assertGreater(track.length, 1000)
        self.assertEqual(track.pose(0), track.pose(track.length))
        for fraction in (0, 0.2, 0.5, 0.9):
            s = track.length * fraction
            x, y, _ = track.pose(s)
            projection = track.project(x, y)
            self.assertAlmostEqual(projection.distance, 0, places=6)
            self.assertAlmostEqual(projection.progress, s, places=6)
        x, y, angle = track.pose(100)
        edge = track.project(x - math.sin(angle) * 20, y + math.cos(angle) * 20)
        self.assertGreater(edge.distance, track.width / 2)

    def test_laps_need_ordered_checkpoints_no_reverse_or_shortcuts(self):
        timer = LapTimer(1000)
        for i, s in enumerate(range(10, 1010, 10), 1):
            timer.update(s % 1000, i * 10000)
        self.assertEqual(timer.laps, 1)
        self.assertEqual(timer.last_lap_s, 1)
        for s in (990, 980, 990, 0):
            timer.update(s, 2_000_000)
        self.assertEqual(timer.laps, 1)
        # Objetí mimo trať není platné kolo.
        for i, s in enumerate(range(10, 1010, 10), 1):
            timer.update(s % 1000, 2_000_000 + i * 10000, on_track=s != 500)
        self.assertEqual(timer.laps, 1)
        self.assertTrue(timer.valid)  # Nové kolo po startu lze znovu zajet platně.

    def test_surface_comes_from_position_and_reset_clears_laps(self):
        e = Engine(vehicle=True)
        e.enable_driving()
        e.driving.x, e.driving.y = 0, 70
        e.driving.before_step(e.vehicle)
        e.driving.step(e.vehicle, 0.001, 1000)
        e.driving.before_step(e.vehicle)
        self.assertTrue(e.driving.off_track)
        self.assertEqual(e.vehicle.mu_left, 0.28)
        self.assertGreater(e.vehicle.surface_drag_n, 0)
        e.reset()
        self.assertEqual(e.driving.progress, 0)
        self.assertFalse(e.driving.off_track)
        self.assertTrue(e.paused)
        self.assertEqual(e.vehicle.selector, "D")


class JoypadTests(unittest.TestCase):
    def test_trigger_defaults_deadzone_inversion_and_shared_axis(self):
        m = Mapping()
        self.assertEqual(controls({}, m)["throttle"], 0)
        self.assertEqual(
            controls({5: -1, 2: -1, 0: 0.02}, m), {"throttle": 0, "brake": 0, "steer_deg": 0}
        )
        self.assertEqual(
            controls({5: 1, 2: 1, 0: 1}, m), {"throttle": 1, "brake": 1, "steer_deg": -30}
        )
        self.assertEqual(controls({0: 1}, Mapping(steer_invert=True))["steer_deg"], 30)
        m = Mapping(throttle_axis=1, brake_axis=1, throttle_mode="negative", brake_mode="positive")
        self.assertEqual(controls({1: -1}, m)["throttle"], 1)
        self.assertEqual(controls({1: -1}, m)["brake"], 0)
        self.assertEqual(controls({1: 1}, m)["brake"], 1)

    def test_partial_events_initial_buttons_and_press_edges(self):
        joy = Joypad()
        raw = EVENT.pack(0, -32767, 0x82, 5)
        joy.feed(raw[:3])
        self.assertNotIn(5, joy.axes)
        joy.feed(raw[3:])
        self.assertEqual(joy.axes[5], -1)
        joy.feed(EVENT.pack(0, 1, 0x81, 7))
        self.assertFalse(joy.pressed)
        joy.feed(EVENT.pack(1, 0, 1, 7) + EVENT.pack(2, 1, 1, 7))
        self.assertEqual(joy.pressed, {7})

    def test_nonblocking_read_disconnect_and_reconnect_state(self):
        reader, writer = os.pipe()
        os.set_blocking(reader, False)
        joy = Joypad()
        joy.fd = reader
        try:
            self.assertTrue(joy.poll())  # EAGAIN není odpojení.
            os.write(
                writer,
                EVENT.pack(1, 32767, 2, 0)
                + EVENT.pack(2, -32767, 2, 2)
                + EVENT.pack(3, -32767, 2, 5),
            )
            self.assertTrue(joy.poll())
            self.assertTrue(joy.ready(Mapping()))
            os.close(writer)
            writer = None
            self.assertFalse(joy.poll())
            self.assertIsNone(joy.fd)
            self.assertEqual(joy.axes, {})
            self.assertEqual(controls(joy.axes, Mapping())["throttle"], 0)
        finally:
            joy.close()
            if writer is not None:
                os.close(writer)

    def test_mapping_validation_and_persistence(self):
        for values in (
            {"deadzone": 1},
            {"steer_axis": -1},
            {"sensitivity": float("nan")},
            {"reset_button": 7},
            {"throttle_mode": "invalid"},
            {"steer_invert": 1},
        ):
            with self.assertRaises((ValueError, TypeError)):
                Mapping(**values)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "mapping.json"
            Mapping(steer_axis=3).save(path)
            self.assertEqual(Mapping.load(path).steer_axis, 3)
        joy = Joypad("/nonexistent/joypad")
        self.assertFalse(joy.open())
        self.assertTrue(joy.error)


class DrivingEngineTests(unittest.TestCase):
    def test_actual_ecu_moves_car_on_track_and_turns(self):
        e = Engine(vehicle=True)
        e.enable_driving()
        bridge = MockBridge(e)
        try:
            bridge.start()
            e.resume_driving()
            initial = e.driving.heading
            for i in range(5000):
                if i % 50 == 0:
                    e.drive_input(0.7, 0, 2 if i > 2500 else 0, "demo")
                e.step()
            state = e.snapshot()
            self.assertGreater(state["driving"]["x_m"], 10)
            self.assertGreater(state["vehicle"]["speed_kmh"], 10)
            self.assertGreater(state["driving"]["heading_rad"], initial + 0.01)
            self.assertEqual(state["simulation_time_us"], 5_000_000)
            self.assertTrue(bridge.diagnostics()["controller"]["synced"])
            json.dumps(state, allow_nan=False)
        finally:
            bridge.close()

    def test_input_watchdog_pause_and_no_automatic_resume(self):
        e = Engine(vehicle=True)
        e.enable_driving()
        e.resume_driving()
        e.drive_input(0.5, 0, 0)
        for _ in range(600):
            e.step()
        self.assertTrue(e.paused)
        self.assertFalse(e.driving.armed)
        self.assertEqual(e.model.throttle, 0)
        self.assertEqual(e.vehicle.brake, 1)
        before = e.snapshot()
        for _ in range(100):
            e.step()
        self.assertEqual(before, e.snapshot())
        e.drive_input(0, 0, 0)
        self.assertTrue(e.paused)
        e.resume_driving()
        e.step()
        self.assertFalse(e.paused)

    def test_invalid_input_does_not_change_controls_and_disable_clears_session(self):
        e = Engine(vehicle=True)
        e.enable_driving()
        for values in ((float("nan"), 0, 0), (0.5, -1, 0), (0.5, 0, 40)):
            with self.assertRaises(ValueError):
                e.drive_input(*values)
        self.assertEqual(e.model.throttle, 0)
        e.set_vehicle_enabled(False)
        self.assertIsNone(e.driving)
        self.assertNotIn("driving", e.snapshot())

    def test_session_snapshot_does_not_advance_time(self):
        session = DrivingSession()
        self.assertEqual(session.snapshot(), session.snapshot())
        self.assertEqual(session.last_time_us, 0)

    def test_panel_disconnection_pauses_and_releases_controls(self):
        from types import SimpleNamespace

        from driving_gui import DrivingPanel

        e = Engine(vehicle=True)
        e.enable_driving()
        e.resume_driving()
        e.drive_input(1, 0, 10, "joypad")
        panel = object.__new__(DrivingPanel)
        panel.app = SimpleNamespace(engine=e)
        panel.source = Mock()
        panel.source.get.return_value = "Joypad"
        panel.joypad = Joypad("/nonexistent/joypad")
        panel.mapping = Mapping()
        panel.profile_note = "Test"
        panel.mapped_status = Mock()
        panel.input_status = Mock()
        panel.status = Mock()
        panel.keys = set()
        panel.key_steer = 0
        panel.check_dialog = None
        panel.last_active = True
        panel.poll_input(True)
        self.assertTrue(e.paused)
        self.assertFalse(e.driving.armed)
        self.assertEqual(e.model.throttle, 0)
        self.assertEqual(e.vehicle.brake, 1)

    def test_focus_check_accepts_internal_combobox_popdown_and_pauses_only_outside_app(self):
        from types import SimpleNamespace

        from driving_gui import DrivingPanel

        panel = object.__new__(DrivingPanel)
        panel.app = SimpleNamespace(engine=SimpleNamespace(driving=SimpleNamespace(armed=True)))
        panel.parent = Mock()
        panel.parent.after_idle.side_effect = lambda callback: callback()
        panel.parent.winfo_exists.return_value = True
        root = panel.parent.winfo_toplevel.return_value
        root._w = "."
        root.focus_displayof.side_effect = KeyError("popdown")
        root.tk.call.return_value = ".!notebook.!combobox.popdown.f.l"
        panel.pause = Mock()
        panel.window_focus_lost()
        panel.pause.assert_not_called()
        root.focus_displayof.assert_not_called()
        root.tk.call.assert_called_with("focus", "-displayof", ".")
        root.tk.call.return_value = ""
        panel.window_focus_lost()
        panel.pause.assert_called_once()

    def test_focus_check_ignores_inactive_driving_and_destroyed_window(self):
        import tkinter as tk
        from types import SimpleNamespace

        from driving_gui import DrivingPanel

        panel = object.__new__(DrivingPanel)
        panel.app = SimpleNamespace(engine=SimpleNamespace(driving=None))
        panel.parent = Mock()
        panel.parent.after_idle.side_effect = lambda callback: callback()
        panel.pause = Mock()
        panel.window_focus_lost()
        panel.parent.winfo_exists.assert_not_called()
        panel.app.engine.driving = SimpleNamespace(armed=True)
        panel.parent.winfo_exists.side_effect = tk.TclError("application destroyed")
        panel.window_focus_lost()
        panel.pause.assert_not_called()

    def test_track_render_uses_physical_position(self):
        from driving_gui import DrivingPanel

        panel = object.__new__(DrivingPanel)
        panel.canvas = Mock()
        panel.canvas.winfo_width.return_value = 1000
        panel.canvas.winfo_height.return_value = 600
        panel.track = Circuit()
        panel.view = Mock()
        panel.view.get.return_value = "Mapa okruhu"
        panel.follow = Mock()
        panel.follow.get.return_value = False
        panel.status = Mock()
        panel.pause_button = Mock()
        e = Engine(vehicle=True)
        e.enable_driving()
        panel.refresh(e.snapshot())
        self.assertTrue(
            any(
                c.kwargs.get("tags") == "race:car"
                for c in panel.canvas.create_polygon.call_args_list
            )
        )
        self.assertTrue(
            any(
                c.kwargs.get("tags") == "track:road"
                for c in panel.canvas.create_line.call_args_list
            )
        )


@unittest.skipUnless(os.environ.get("ECU_TEST_GUI") == "1", "requires Tk display")
class DrivingGuiTests(unittest.TestCase):
    def test_keyboard_focus_pause_and_circuit_tab(self):
        import tkinter as tk

        from gui import EngineView
        from supervisor import Supervisor

        app = Supervisor(vehicle=True)
        app.engine.enable_driving()
        root = tk.Tk()
        view = EngineView(root, app)
        try:
            root.update()
            panel = view.driving_panel
            panel.source.set("Klávesnice")
            panel.toggle_pause()
            panel.keys.add("up")
            panel.poll_input(True)
            app.engine.step()
            panel.view.set("Mapa okruhu")
            panel.refresh(app.engine.snapshot())
            self.assertEqual(app.engine.model.throttle, 1)
            self.assertTrue(panel.canvas.find_withtag("race:car"))
            panel.poll_input(False)
            self.assertTrue(app.engine.paused)
        finally:
            view.close()
            app.close()
