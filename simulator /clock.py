"""Virtuální hodiny; žádná závislost na transportu ani modelu."""
from dataclasses import dataclass

@dataclass
class SimulationClock:
    step_us: int = 1000
    time_us: int = 0

    def __post_init__(self):
        if type(self.step_us) is not int or not 1 <= self.step_us <= 100000:
            raise ValueError('step_us must be an integer in 1..100000')

    def advance(self):
        self.time_us += self.step_us
        return self.time_us

    def reset(self):
        self.time_us = 0
