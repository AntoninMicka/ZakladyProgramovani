"""Sekvence nad pojmenovanými prvky, návrat do klidu a potlačení jízdních akcí."""

import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from gamepad_check import GamepadCheck, sequence
from joypad import Joypad

BUTTONS = [0x130, 0x131, 0x133, 0x134, 0x136, 0x137, 0x138, 0x139, 0x13A, 0x13B]


def pad(codes=None):
    joy = Joypad()
    joy.axis_codes = codes or [0, 1, 2, 3, 4, 5, 16, 17]
    joy.button_codes = list(BUTTONS)
    joy.axes = {i: (-1.0 if code in (2, 5) else 0.0) for i, code in enumerate(joy.axis_codes)}
    joy.buttons = dict.fromkeys(range(len(BUTTONS)), False)
    return joy


class GamepadCheckTests(unittest.TestCase):
    def test_sequence_matches_described_controls(self):
        steps = sequence()
        self.assertEqual(len(steps), 20)
        self.assertEqual(sum(s.key.startswith("left_") for s in steps), 4)
        self.assertEqual(sum(s.key.startswith("right_") for s in steps), 4)
        self.assertEqual(sum(s.key.startswith("dpad_") for s in steps), 4)
        self.assertEqual(sum(s.key.startswith("face_") for s in steps), 4)
        self.assertEqual(sum(s.key.startswith("lever_") for s in steps), 2)
        self.assertEqual(sum(s.key.startswith("trigger_") for s in steps), 2)

    def test_complete_sequence_uses_abstraction_for_both_axis_orders(self):
        for codes in ([0, 1, 2, 3, 4, 5, 16, 17], [0, 1, 3, 2, 5, 4, 16, 17]):
            with self.subTest(codes=codes):
                joy = pad(codes)
                state = joy.semantic_state()
                check = GamepadCheck(state, "/dev/input/js0", "Test pad")
                for now, step in enumerate(check.steps):
                    binding = state.bindings[step.key]
                    if binding["type"] == "axis":
                        joy.axes[binding["index"]] = (
                            1 if step.key.startswith("lever_") else step.target
                        )
                    else:
                        joy.buttons[binding["index"]] = True
                    check.observe(joy.semantic_state(), now)
                    self.assertEqual(check.phase, "release")
                    index = check.index
                    check.observe(joy.semantic_state(), now + 0.5)
                    self.assertEqual(check.index, index)  # Držený vstup nelze vydávat za dokončený.
                    if binding["type"] == "axis":
                        joy.axes[binding["index"]] = -1 if step.key.startswith("lever_") else 0
                    else:
                        joy.buttons[binding["index"]] = False
                    check.observe(joy.semantic_state(), now + 0.6)
                    check.observe(joy.semantic_state(), now + 0.9)
                    self.assertEqual(check.index, index + 1)
                report = check.report()
                self.assertTrue(report["complete"])
                self.assertEqual(report["passed"], 20)
                self.assertTrue(all(r["returned_to_rest"] for r in report["results"]))
                json.dumps(report, allow_nan=False)

    def test_wrong_stick_or_direction_does_not_pass(self):
        joy = pad()
        check = GamepadCheck(joy.semantic_state())
        joy.axes[3] = -1  # Pravá páčka místo levé.
        check.observe(joy.semantic_state(), 0)
        self.assertEqual(check.phase, "action")
        self.assertIn("pravá", check.message)
        joy.axes[3] = 0
        joy.axes[0] = 1  # Špatný směr.
        check.observe(joy.semantic_state(), 1)
        self.assertEqual(check.index, 0)
        self.assertEqual(check.phase, "action")

    def test_skip_failure_disconnect_and_partial_report_are_explicit(self):
        joy = pad()
        check = GamepadCheck(joy.semantic_state())
        check.mark("failed")
        check.observe(joy.semantic_state(), 0)
        check.observe(joy.semantic_state(), 0.3)
        check.mark("skipped")
        check.disconnected()
        report = check.report()
        self.assertFalse(report["complete"])
        self.assertEqual(report["passed"], 0)
        self.assertEqual(report["failed"], 1)
        self.assertEqual(report["skipped"], 1)
        self.assertTrue(report["error"])
        report["results"].clear()
        self.assertEqual(len(check.results), 2)

    def test_baseline_requires_released_controls_and_unknown_is_not_zero(self):
        joy = pad()
        joy.buttons[0] = True
        with self.assertRaises(ValueError):
            GamepadCheck(joy.semantic_state())
        joy = Joypad()
        state = joy.semantic_state()
        self.assertTrue(all(v is None for v in state.values.values()))
        with self.assertRaises(ValueError):
            GamepadCheck(state)

    def test_dpad_buttons_and_digital_one_way_controls_are_abstracted(self):
        joy = pad([0, 1, 2, 5])
        joy.button_codes += [0x220, 0x221, 0x222, 0x223]
        joy.buttons = dict.fromkeys(range(len(joy.button_codes)), False)
        state = joy.semantic_state()
        self.assertEqual(state.bindings["lever_left"]["type"], "button")
        joy.buttons[joy.button_codes.index(0x222)] = True
        self.assertEqual(joy.semantic_state().values["dpad_x"], -1)
        joy.buttons[joy.button_codes.index(0x222)] = False
        joy.buttons[joy.button_codes.index(0x223)] = True
        self.assertEqual(joy.semantic_state().values["dpad_x"], 1)

    def test_active_verification_never_dispatches_buttons_to_driving(self):
        from driving_gui import DrivingPanel

        panel = object.__new__(DrivingPanel)
        panel.joypad = Mock()
        panel.joypad.poll.return_value = True
        panel.check_dialog = Mock()
        panel.app = SimpleNamespace(engine=Mock())
        panel.send_input = Mock()
        panel.poll_input(True)
        panel.check_dialog.update.assert_called_once_with(panel.joypad, True)
        panel.app.engine.reset.assert_not_called()
        panel.app.engine.resume_driving.assert_not_called()
        panel.send_input.assert_not_called()
