"""SVG, význam živých údajů a skutečná interakce nové záložky."""

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from xml.etree import ElementTree as ET

from engine import Engine
from engine_diagram import SVG_PATH, SvgCanvas, component_details


class EngineDiagramTests(unittest.TestCase):
    def test_svg_has_transparent_background_and_required_parts(self):
        root = ET.parse(SVG_PATH).getroot()
        self.assertEqual(root.attrib["viewBox"], "0 0 1400 940")
        keys = {node.get("data-part") for node in root.iter()}
        self.assertTrue(
            {"ecu", "ckp", "cmp", "map", "tps", "iat", "clt", "lambda", "pedal", "load"} <= keys
        )
        for channel in range(4):
            self.assertIn(f"injector-{channel}", keys)
            self.assertIn(f"coil-{channel}", keys)
        self.assertFalse(
            any(node.get("width") == "1400" and node.get("height") == "940" for node in list(root))
        )
        self.assertTrue(any(node.get("fill-opacity") == ".09" for node in root.iter()))
        self.assertTrue(
            all(node.tag.rsplit("}", 1)[-1] in SvgCanvas.SUPPORTED for node in root.iter())
        )

    def test_sensor_values_and_unavailable_ecu_are_not_invented(self):
        engine = Engine()
        state = engine.snapshot()
        for key in ("ckp", "cmp", "map", "tps", "iat", "clt", "lambda", "pedal", "load", "engine"):
            title, explanation, values = component_details(key, state, {}, engine.signals)
            self.assertTrue(title and explanation and values)
        values = component_details("ecu", state, {}, engine.signals)[2]
        self.assertIn("nejsou", values)
        state["map_kpa"] = 88.5
        self.assertIn("88.5 kPa", component_details("map", state, {}, engine.signals)[2])

    def test_active_and_absent_cylinders_have_correct_details(self):
        engine = Engine()
        state = engine.snapshot()
        state["injector_active"] = [0]
        state["last_injection_us"] = {0: 1050}
        detail = component_details("injector-0", state, {}, engine.signals)[2]
        self.assertIn("ano", detail)
        self.assertIn("1050 µs", detail)
        state["cylinders"] = 2
        self.assertIn("není aktivní", component_details("coil-3", state, {}, engine.signals)[2])


@unittest.skipUnless(
    os.environ.get("ECU_TEST_GUI") == "1", "enable with ECU_TEST_GUI=1 and a display"
)
class EngineDiagramGuiTests(unittest.TestCase):
    def test_vector_tab_click_zoom_highlight_and_svg_export(self):
        import tkinter as tk
        from gui import EngineView
        from supervisor import Supervisor

        root = tk.Tk()
        app = Supervisor()
        view = EngineView(root, app)
        try:
            view.notebook.select(view.diagram_page)
            root.update()
            panel = view.engine_diagram
            self.assertIn(
                "Schéma motoru", [view.notebook.tab(tab, "text") for tab in view.notebook.tabs()]
            )
            shapes = len(panel.canvas.find_withtag("shape"))
            expected = sum(
                node.tag.rsplit("}", 1)[-1] not in ("svg", "g", "title", "desc")
                for node in ET.parse(SVG_PATH).getroot().iter()
            )
            self.assertEqual(shapes, expected)
            item = panel.canvas.find_withtag("part:map")[0]
            x1, y1, x2, y2 = panel.canvas.coords(item)
            panel.canvas.event_generate(
                "<Button-1>", x=round((x1 + x2) / 2), y=round((y1 + y2) / 2)
            )
            self.assertEqual(panel.selected, "map")
            self.assertIn("MAP", panel.title.get())
            panel.zoom.set("150 %")
            panel.redraw()
            self.assertEqual(
                tuple(map(float, panel.canvas.cget("scrollregion").split())), (0, 0, 2100, 1410)
            )
            self.assertEqual(len(panel.canvas.find_withtag("shape")), shapes)
            state = app.engine.snapshot()
            state["injector_active"] = [0]
            state["last_injection_us"] = {0: 1050}
            panel.refresh(state, app.bridge.diagnostics())
            active = [item for item, key, _ in panel.renderer.active_items if key == "injector-0"]
            self.assertEqual(panel.canvas.itemcget(active[0], "fill"), "#fb923c")
            panel.select("injector-0")
            self.assertIn("1050 µs", panel.values.get())
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "motor.svg"
                with patch("tkinter.filedialog.asksaveasfilename", return_value=str(path)):
                    panel.save_svg()
                self.assertEqual(path.read_bytes(), SVG_PATH.read_bytes())
        finally:
            view.close()
            app.close()
