import tempfile
import unittest
from pathlib import Path
from signals import SignalGenerator
from tools.check_vcd import check

class VCDCheckerTests(unittest.TestCase):
    def write_capture(self,path,missing=2):
        events=[(0,'a',1),(0,'b',1),(0,'c',0),(0,'d',0)]
        for edge in SignalGenerator(missing=missing).edges(0,2880,0,480000):
            events.append((edge.simulation_time_us,'a' if edge.signal=='CKP' else 'b',edge.level))
        for t in range(10000,450000,30000):
            events.extend([(t,'c',1),(t+3000,'c',0),(t,'d',1),(t+2000,'d',0)])
        header='$timescale 1 us $end\n'
        header+='\n'.join(f'$var wire 1 {code} D{i} $end' for i,code in enumerate('abcd'))
        body='\n$enddefinitions $end\n'
        body+='\n'.join(f'#{t}\n{level}{code}' for t,code,level in sorted(events))
        path.write_text(header+body+'\n')

    def test_accept_correct_capture(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'capture.vcd';self.write_capture(p)
            result=check(p,1000)
            self.assertEqual(result['ckp_max_interval_error_us'],0)
            self.assertEqual(result['output_pulses']['D2']['median_width_us'],3000)

    def test_reject_missing_gap(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'capture.vcd';self.write_capture(p,missing=0)
            with self.assertRaises(ValueError):check(p,1000)
