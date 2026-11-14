"""Úhlově řízené hrany; interval (počáteční úhel, koncový úhel]."""
from dataclasses import dataclass, asdict
import math

@dataclass(frozen=True)
class Edge:
    simulation_time_us: int
    signal: str
    channel: int
    level: int

    def data(self):
        return asdict(self)

class SignalGenerator:
    def __init__(self, teeth=60, missing=2, cmp_positions=(0.0,), cmp_width=12.0):
        if type(teeth) is not int or type(missing) is not int or not 0 <= missing < teeth <= 360:
            raise ValueError('invalid tooth wheel')
        if not 0 < cmp_width < 720 or not cmp_positions:
            raise ValueError('invalid CMP pulses')
        positions = sorted(float(x) for x in cmp_positions)
        if any(not math.isfinite(x) or not 0 <= x < 720 for x in positions):
            raise ValueError('CMP position outside cycle')
        if any((positions[(i+1) % len(positions)] - p) % 720 < cmp_width
               for i, p in enumerate(positions)) and len(positions) > 1:
            raise ValueError('overlapping CMP pulses')
        self.teeth, self.missing = teeth, missing
        self.cmp_positions, self.cmp_width = tuple(positions), cmp_width

    def levels(self, angle=0.0):
        phase = angle % 360 / (360 / self.teeth)
        return {'CKP': int(int(phase) < self.teeth-self.missing and phase % 1 < .5),
                'CMP': int(any((angle-p) % 720 < self.cmp_width for p in self.cmp_positions))}

    def edges(self, start_angle, end_angle, start_us, end_us):
        if end_angle <= start_angle:
            return ()
        result = []
        patterns = [('CKP', 360.0, [(i*360/self.teeth + offset, level)
                    for i in range(self.teeth-self.missing)
                    for offset, level in ((0, 1), (180/self.teeth, 0))]),
                    ('CMP', 720.0, [(a % 720, level) for p in self.cmp_positions
                     for a, level in ((p, 1), (p+self.cmp_width, 0))])]
        for signal, period, pattern in patterns:
            for base in range(math.floor(start_angle/period), math.floor(end_angle/period)+1):
                for phase, level in pattern:
                    angle = base*period+phase
                    if start_angle < angle <= end_angle:
                        fraction = (angle-start_angle)/(end_angle-start_angle)
                        result.append(Edge(round(start_us+fraction*(end_us-start_us)), signal, 0, level))
        return tuple(sorted(result, key=lambda e: (e.simulation_time_us, e.signal, e.level)))
