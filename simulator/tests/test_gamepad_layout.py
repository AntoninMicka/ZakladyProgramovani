"""Metadata Linux ABS/BTN místo pevného pořadí os; Xbox-like, DS4 a D-input."""

import struct
import unittest
from unittest.mock import patch

from joypad import EVENT, Joypad, Mapping, controls, detect_mapping

BUTTONS = [0x130, 0x131, 0x133, 0x134, 0x136, 0x137, 0x13A, 0x13B]


class GamepadLayoutTests(unittest.TestCase):
    def test_xbox_like_and_ps4_use_actual_axis_order(self):
        for codes, expected in (
            ([0, 1, 2, 3, 4, 5, 16, 17], (5, 2)),
            ([0, 1, 3, 2, 5, 4, 16, 17], (4, 3)),
        ):
            with self.subTest(codes=codes):
                mapping, reason = detect_mapping(codes, BUTTONS)
                self.assertIsNotNone(mapping, reason)
                self.assertEqual((mapping.throttle_axis, mapping.brake_axis), expected)
                axes = {i: (-1 if code in (2, 5) else 0) for i, code in enumerate(codes)}
                self.assertEqual(controls(axes, mapping)["throttle"], 0)
                self.assertEqual(controls(axes, mapping)["brake"], 0)
                axes[mapping.throttle_axis] = 1
                self.assertEqual(controls(axes, mapping)["throttle"], 1)
                self.assertEqual(controls(axes, mapping)["brake"], 0)

    def test_dinput_right_stick_is_not_misinterpreted_as_half_throttle(self):
        mapping, reason = detect_mapping([0, 1, 2, 5, 16, 17], BUTTONS)
        self.assertIn("Páčka", reason)
        self.assertEqual(mapping.throttle_axis, mapping.brake_axis)
        self.assertEqual(controls({0: 0, 1: 0, 2: 0, 3: 0}, mapping)["throttle"], 0)
        self.assertEqual(controls({0: 0, 1: -1}, mapping)["throttle"], 1)
        self.assertEqual(controls({0: 0, 1: 1}, mapping)["brake"], 1)

    def test_digital_l2_r2_fallback_and_ready(self):
        codes = BUTTONS + [0x138, 0x139]
        mapping, _ = detect_mapping([0, 1, 2, 5], codes)
        joy = Joypad()
        joy.fd = 123
        joy.axes = {0: 0}
        joy.buttons = {8: False, 9: False}
        self.assertTrue(joy.ready(mapping))
        self.assertTrue(joy.neutral(mapping))
        self.assertEqual(controls(joy.axes, mapping, {9: True})["throttle"], 1)
        self.assertEqual(controls(joy.axes, mapping, {8: True})["brake"], 1)
        joy.fd = None

    def test_button_semantics_and_trigger_deadzone(self):
        buttons = list(reversed(BUTTONS))
        mapping, _ = detect_mapping([0, 1, 2, 3, 4, 5], buttons)
        self.assertEqual(mapping.pause_button, buttons.index(0x13B))
        self.assertEqual(mapping.drive_button, buttons.index(0x137))
        self.assertEqual(mapping.reset_button, buttons.index(0x130))
        self.assertEqual(controls({0: 0, 2: -0.96, 5: -0.96}, mapping)["throttle"], 0)
        joy = Joypad()
        joy.fd = 123
        joy.axes = {0: 0, 2: -1, 5: -1}
        self.assertTrue(joy.neutral(mapping))
        joy.axes[5] = 1
        self.assertFalse(joy.neutral(mapping))
        joy.fd = None

    def test_ioctl_reads_metadata_for_ps4_reordered_axes(self):
        codes = [0, 1, 3, 2, 5, 4, 16, 17]

        def ioctl(fd, request, buffer, mutate):
            self.assertEqual(fd, 123)
            if request == 0x80016A11:
                buffer[0] = len(codes)
            elif request == 0x80016A12:
                buffer[0] = len(BUTTONS)
            elif request == 0x80406A32:
                buffer[: len(codes)] = bytes(codes)
            elif request == 0x84006A34:
                buffer[: len(BUTTONS) * 2] = struct.pack("=" + str(len(BUTTONS)) + "H", *BUTTONS)
            elif request == 0x80806A13:
                buffer[:20] = b"Wireless Controller\0"
            else:
                self.fail(f"Unexpected ioctl {request:x}")

        joy = Joypad()
        joy.fd = 123
        with patch("fcntl.ioctl", side_effect=ioctl):
            joy.read_layout()
        self.assertEqual(joy.name, "Wireless Controller")
        self.assertEqual(joy.detected_mapping.throttle_axis, 4)
        self.assertEqual(joy.detected_mapping.brake_axis, 3)
        for i, code in enumerate(codes):
            joy.feed(EVENT.pack(0, -32767 if code in (2, 5) else 0, 0x82, i))
        self.assertTrue(joy.neutral(joy.detected_mapping))
        joy.fd = None

    def test_auto_profile_respects_explicit_manual_mapping(self):
        from types import SimpleNamespace

        from driving_gui import DrivingPanel

        panel = object.__new__(DrivingPanel)
        detected, reason = detect_mapping([0, 1, 3, 2, 5, 4], BUTTONS)
        panel.joypad = SimpleNamespace(detected_mapping=detected, layout=reason)
        panel.mapping_manual = False
        panel.profile_error = "old error"
        panel.adopt_mapping()
        self.assertEqual(panel.mapping.throttle_axis, 4)
        self.assertEqual(panel.profile_error, "")
        panel.mapping_manual = True
        panel.mapping = Mapping(throttle_axis=1)
        panel.adopt_mapping()
        self.assertEqual(panel.mapping.throttle_axis, 1)
        self.assertEqual(panel.profile_note, "Ruční profil")

    def test_diagnostics_includes_semantic_layout_and_converted_pedals(self):
        import json

        joy = Joypad()
        joy.axis_codes = [0, 1, 3, 2, 5, 4]
        mapping, _ = detect_mapping(joy.axis_codes, BUTTONS)
        joy.axes = {0: 0, 3: -1, 4: 1}
        report = joy.diagnostics(mapping)
        self.assertEqual(report["axis_names"][4], "ABS_RZ")
        self.assertEqual(report["controls"]["throttle"], 1)
        self.assertEqual(report["controls"]["brake"], 0)
        json.dumps(report, allow_nan=False)

    def test_unknown_layout_requests_manual_mapping(self):
        mapping, reason = detect_mapping([3, 4], BUTTONS)
        self.assertIsNone(mapping)
        self.assertIn("ruční", reason)
        mapping, reason = detect_mapping([0, 1, 2, 3, 4, 5], [1, 2, 3])
        self.assertIsNone(mapping)
        for value in (-1, 0.5, float("nan")):
            with self.assertRaises(ValueError):
                Mapping(pedal_deadzone=value)
