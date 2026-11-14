"""Volitelné skutečné Tk widgety; bez přístupu k displeji se testy nespouštějí."""
import os
import unittest
from supervisor import Supervisor
from model import EngineConfig

@unittest.skipUnless(os.environ.get('ECU_TEST_GUI')=='1','enable with ECU_TEST_GUI=1 and a display')
class GuiTests(unittest.TestCase):
    def test_controls_canvas_and_shutdown(self):
        import tkinter as tk
        from gui import EngineView
        root=tk.Tk()
        app=Supervisor()
        view=EngineView(root,app)
        try:
            root.update()
            self.assertTrue(view.canvas.find_all())
            view.throttle.set(70);view.load.set(30);view.command()
            app.engine.step()
            state=app.engine.snapshot()
            self.assertEqual(state['throttle'],.7)
            self.assertEqual(state['load_nm'],30)
            view.toggle_pause();time=app.engine.clock.time_us
            app.engine.step();self.assertEqual(app.engine.clock.time_us,time)
            view.toggle_pause();app.engine.step();self.assertGreater(app.engine.clock.time_us,time)
            view.speed.set('0.02');view.change_speed();self.assertEqual(app.engine.speed,.02)
            view.draw(app.engine.snapshot(),{})
            self.assertTrue(any('EXPANZE'==view.canvas.itemcget(i,'text')
                                for i in view.canvas.find_all() if view.canvas.type(i)=='text'))
        finally:
            view.close();app.close()
        self.assertFalse(app.engine.is_alive())

    def test_sixteen_cylinders_render(self):
        import tkinter as tk
        from gui import EngineView
        root=tk.Tk();app=Supervisor(config=EngineConfig(cylinders=16))
        view=EngineView(root,app)
        try:
            root.update()
            labels=[view.canvas.itemcget(i,'text') for i in view.canvas.find_all()
                    if view.canvas.type(i)=='text']
            self.assertIn('VÁLEC 16',labels)
        finally:view.close();app.close()
