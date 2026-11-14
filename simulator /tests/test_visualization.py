import unittest
from visualization import cylinder_phase, piston_position

class GeometryTests(unittest.TestCase):
    def test_dead_centers_and_period(self):
        self.assertAlmostEqual(piston_position(0),0)
        self.assertAlmostEqual(piston_position(180),1)
        self.assertAlmostEqual(piston_position(360),0)
        for angle in range(720):
            self.assertGreaterEqual(piston_position(angle),0)
            self.assertLessEqual(piston_position(angle),1)
            self.assertAlmostEqual(piston_position(angle),piston_position(angle+360))

    def test_firing_order_and_strokes(self):
        for angle,channel in zip((0,180,360,540),(0,2,3,1)):
            self.assertEqual(cylinder_phase(angle,channel,4),360)
        for angle,phase in zip((0,180,360,540),(360,540,0,180)):
            self.assertEqual(cylinder_phase(angle,0,4),phase)
        self.assertEqual(cylinder_phase(720,0,4),cylinder_phase(0,0,4))

    def test_other_cylinder_counts(self):
        for count in (1,2,6,8,16):
            for channel in range(count):
                phase=cylinder_phase(channel*720/count,channel,count)
                self.assertAlmostEqual(phase,360)
