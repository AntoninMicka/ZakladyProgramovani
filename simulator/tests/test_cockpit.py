"""Perspektiva kokpitu čte fyzický stav auta; bez nutnosti grafického displeje."""

import copy
import math
import unittest
from unittest.mock import Mock

from cockpit import CockpitView, clip_near
from engine import Engine


class CockpitTests(unittest.TestCase):
    def test_near_plane_clips_polygon_without_division_by_zero(self):
        points = clip_near([(-1, -2), (1, -2), (1, 5), (-1, 5)])
        self.assertEqual(len(points), 4)
        self.assertTrue(all(p[1] >= 2 for p in points))
        self.assertEqual(clip_near([(-1, -2), (1, -2), (1, 0)]), [])
        self.assertAlmostEqual(CockpitView.camera_point(10, 0, 0, 0, 0)[1], 10)
        self.assertLess(
            CockpitView.camera_point(10, 5, 0, 0, 0)[0], 0
        )  # Vlevo ve světě → vlevo v okně.

    def test_landscape_road_dashboard_and_wheel_render_at_different_track_positions(self):
        canvas = Mock()
        cockpit = CockpitView(canvas)
        engine = Engine(vehicle=True)
        engine.enable_driving()
        state = engine.snapshot()
        for progress in (0, 250, 700, 1200):
            with self.subTest(progress=progress):
                x, y, heading = cockpit.track.pose(progress)
                state["driving"].update(x_m=x, y_m=y, heading_rad=heading)
                unchanged = copy.deepcopy(state)
                canvas.reset_mock()
                cockpit.draw(state, 1100, 650)
                tags = {call.kwargs.get("tags") for call in canvas.create_polygon.call_args_list}
                self.assertTrue({"cockpit:road", "cockpit:dashboard", "cockpit:landscape"} <= tags)
                self.assertTrue(
                    any(
                        call.kwargs.get("tags") == "cockpit:wheel"
                        for call in canvas.create_oval.call_args_list
                    )
                )
                for call in canvas.create_polygon.call_args_list:
                    self.assertTrue(all(math.isfinite(value) for value in call.args))
                self.assertEqual(state, unchanged)

    def test_steering_changes_spokes_and_missing_can_shows_dashes(self):
        canvas = Mock()
        cockpit = CockpitView(canvas)
        engine = Engine(vehicle=True)
        engine.enable_driving()
        state = engine.snapshot()
        cockpit.draw(state, 1100, 650)
        first = [
            c.args
            for c in canvas.create_line.call_args_list
            if c.kwargs.get("tags") == "cockpit:spoke"
        ]
        canvas.reset_mock()
        state["vehicle"]["steer_deg"] = 2
        cockpit.draw(state, 1100, 650)
        second = [
            c.args
            for c in canvas.create_line.call_args_list
            if c.kwargs.get("tags") == "cockpit:spoke"
        ]
        self.assertNotEqual(first, second)
        self.assertLess(second[0][3], second[0][1])  # Levý rejd otáčí volant proti směru hodin.
        self.assertTrue(
            any("—" in c.kwargs.get("text", "") for c in canvas.create_text.call_args_list)
        )
