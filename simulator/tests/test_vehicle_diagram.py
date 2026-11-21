"""Schéma vozu, pravdivost symbolu na CAN a volitelná skutečná Tk interakce."""

import math
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from xml.etree import ElementTree as ET

from engine import Engine
from engine_diagram import SvgCanvas
from vehicle_diagram import (
    PARTS,
    SVG_PATH,
    component_details,
    draw_symbol,
    symbol_state,
    wheel_color,
    wheel_polygon,
)


class VehicleDiagramTests(unittest.TestCase):
    def running_engine(self):
        engine = Engine(vehicle=True)
        engine.vehicle.command({"steer_deg": 15, "brake": 0.4})
        for _ in range(100):
            engine.step()
        return engine

    def test_svg_is_supported_and_all_parts_are_inspectable(self):
        root = ET.parse(SVG_PATH).getroot()
        self.assertEqual(root.attrib["viewBox"], "0 0 1400 940")
        keys = {n.get("data-part") for n in root.iter() if n.get("data-part")}
        self.assertEqual(keys, set(PARTS))
        self.assertTrue(all(n.tag.rsplit("}", 1)[-1] in SvgCanvas.SUPPORTED for n in root.iter()))
        self.assertFalse(any(n.get("width") == "1400" and n.get("height") == "940" for n in root))
        engine = self.running_engine()
        for key in keys:
            with self.subTest(key=key):
                title, description, values = component_details(
                    key, engine.snapshot(), {}, engine.signals
                )
                self.assertTrue(title and description and values)
        self.assertIn(
            "bar", component_details("wheel-FL", engine.snapshot(), {}, engine.signals)[2]
        )
        self.assertIn(
            "vypnutý", component_details("gearbox", Engine().snapshot(), {}, engine.signals)[2]
        )

    def test_dashboard_symbol_uses_delivered_values_instead_of_direct_model(self):
        engine = self.running_engine()
        state = engine.snapshot()
        known = symbol_state(state)
        self.assertFalse(known["can_fault"])
        self.assertAlmostEqual(known["steer_deg"], 15, delta=0.1)
        state["vehicle"]["sensors"]["wheel_speed_kmh"]["FL"] = 9876
        state["vehicle"]["sensors"]["brake_pressure_bar"]["FL"] = 9999
        self.assertEqual(symbol_state(state), known)
        engine.vehicle.command({"can_enabled": False})
        for _ in range(400):
            engine.step()
        unavailable = symbol_state(engine.snapshot())
        self.assertTrue(unavailable["can_fault"])
        self.assertIsNone(unavailable["steer_deg"])
        self.assertTrue(
            all(
                w["speed"] is None and w["pressure"] is None and w["color"] == "#94a3b8"
                for w in unavailable["wheels"].values()
            )
        )

    def test_wheel_rotation_preserves_center_and_radius(self):
        zero, turned = wheel_polygon(100, 70, 0), wheel_polygon(100, 70, 25)
        self.assertNotEqual(zero, turned)
        for points in (zero, turned):
            self.assertAlmostEqual(sum(points[::2]) / 4, 100)
            self.assertAlmostEqual(sum(points[1::2]) / 4, 70)
            self.assertAlmostEqual(math.hypot(points[0] - 100, points[1] - 70), math.hypot(7, 17))
        self.assertEqual(wheel_color(None, 30, 0), "#94a3b8")
        self.assertEqual(wheel_color(30, 30, 40), "#ef4444")
        self.assertEqual(wheel_color(50, 30, 0), "#f59e0b")
        self.assertEqual(wheel_color(30, 30, 0), "#14b8a6")

    def test_symbol_renders_all_wheels_and_unknown_data_as_dashes(self):
        canvas = Mock()
        state = Engine().snapshot()
        draw_symbol(canvas, state, 10, 10)
        wheels = [
            c
            for c in canvas.create_polygon.call_args_list
            if str(c.kwargs.get("tags", "")).startswith("symbol:wheel-")
        ]
        self.assertEqual(len(wheels), 4)
        self.assertTrue(all(c.kwargs["fill"] == "#94a3b8" for c in wheels))
        self.assertTrue(
            any("—" in c.kwargs.get("text", "") for c in canvas.create_text.call_args_list)
        )


@unittest.skipUnless(os.environ.get("ECU_TEST_GUI") == "1", "requires Tk display")
class VehicleDiagramGuiTests(unittest.TestCase):
    def test_car_tab_selection_zoom_export_and_live_symbol(self):
        import tkinter as tk

        from gui import EngineView
        from supervisor import Supervisor

        root = tk.Tk()
        app = Supervisor(vehicle=True)
        view = EngineView(root, app)
        try:
            for _ in range(100):
                app.engine.step()
            view.notebook.select(view.diagram_page)
            view.diagram_tabs.select(view.car_drawing_page)
            root.update()
            panel = view.vehicle_diagram
            panel.refresh(app.engine.snapshot(), app.bridge.diagnostics())
            item = panel.canvas.find_withtag("part:wheel-FL")[0]
            x1, y1, x2, y2 = panel.canvas.coords(item)
            panel.canvas.event_generate(
                "<Button-1>", x=round((x1 + x2) / 2), y=round((y1 + y2) / 2)
            )
            self.assertEqual(panel.selected, "wheel-FL")
            self.assertIn("bar", panel.values.get())
            panel.zoom.set("150 %")
            panel.redraw()
            self.assertEqual(
                tuple(map(float, panel.canvas.cget("scrollregion").split())), (0, 0, 2100, 1410)
            )
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "auto.svg"
                with patch("tkinter.filedialog.asksaveasfilename", return_value=str(path)):
                    panel.save_svg()
                self.assertEqual(path.read_bytes(), SVG_PATH.read_bytes())
            view.vehicle_panel.refresh(app.engine.snapshot())
            self.assertTrue(view.vehicle_panel.canvas.find_withtag("symbol:wheel-FL"))
        finally:
            view.close()
            app.close()
