"""Okruh, poloha vozu a kola závodu v témže virtuálním čase jako motor."""

import math
from dataclasses import dataclass


def clamp(value, low, high):
    return max(low, min(high, value))


@dataclass(frozen=True)
class Projection:
    distance: float
    progress: float
    segment: int


class Circuit:
    name = "Výukový okruh"
    width = 14.0

    def __init__(self):
        anchors = [
            (0, 0),
            (180, 0),
            (280, 80),
            (260, 200),
            (160, 220),
            (100, 140),
            (30, 130),
            (-60, 230),
            (-200, 220),
            (-280, 130),
            (-260, 30),
            (-150, 0),
        ]
        self.points = []
        # Uzavřená Catmull–Rom křivka: plynulé zatáčky mezi opěrnými body.
        for i in range(len(anchors)):
            p0, p1, p2, p3 = [anchors[j % len(anchors)] for j in (i - 1, i, i + 1, i + 2)]
            for sample in range(16):
                t = sample / 16
                self.points.append(
                    tuple(
                        0.5
                        * (
                            2 * p1[k]
                            + (-p0[k] + p2[k]) * t
                            + (2 * p0[k] - 5 * p1[k] + 4 * p2[k] - p3[k]) * t * t
                            + (-p0[k] + 3 * p1[k] - 3 * p2[k] + p3[k]) * t * t * t
                        )
                        for k in (0, 1)
                    )
                )
        self.lengths = []
        self.offsets = [0.0]
        for a, b in zip(self.points, self.points[1:] + self.points[:1]):
            length = math.hypot(b[0] - a[0], b[1] - a[1])
            self.lengths.append(length)
            self.offsets.append(self.offsets[-1] + length)
        self.length = self.offsets[-1]

    def pose(self, progress):
        s = progress % self.length
        i = next(i for i in range(len(self.points)) if self.offsets[i + 1] > s)
        a, b = self.points[i], self.points[(i + 1) % len(self.points)]
        t = (s - self.offsets[i]) / self.lengths[i]
        return (
            a[0] + (b[0] - a[0]) * t,
            a[1] + (b[1] - a[1]) * t,
            math.atan2(b[1] - a[1], b[0] - a[0]),
        )

    def project(self, x, y, hint=None):
        indices = (
            range(len(self.points))
            if hint is None
            else ((hint + j) % len(self.points) for j in range(-8, 9))
        )
        best = None
        for i in indices:
            a, b = self.points[i], self.points[(i + 1) % len(self.points)]
            dx, dy = b[0] - a[0], b[1] - a[1]
            t = clamp(((x - a[0]) * dx + (y - a[1]) * dy) / self.lengths[i] ** 2, 0, 1)
            distance = math.hypot(x - a[0] - t * dx, y - a[1] - t * dy)
            candidate = Projection(
                distance, (self.offsets[i] + t * self.lengths[i]) % self.length, i
            )
            if best is None or distance < best.distance:
                best = candidate
        return best


class LapTimer:
    """Kolo uzná jen průjezd čtvrtinami okruhu v pořadí a pak startem vpřed."""

    def __init__(self, length):
        self.length = length
        self.previous = 0.0
        self.checkpoint = 1
        self.started_us = 0
        self.laps = 0
        self.last_lap_s = self.best_lap_s = None
        self.valid = True

    def update(self, progress, now_us, on_track=True):
        delta = (progress - self.previous + self.length / 2) % self.length - self.length / 2
        old = self.previous
        self.previous = progress
        if not on_track:
            self.valid = False
        if delta <= 0 or delta > self.length / 8:
            return
        if self.checkpoint <= 3:
            target = self.length * self.checkpoint / 4
            if old <= target <= progress:
                self.checkpoint += 1
        if progress < old:
            if self.checkpoint == 4 and self.valid:
                lap = (now_us - self.started_us) / 1e6
                self.laps += 1
                self.last_lap_s = lap
                self.best_lap_s = lap if self.best_lap_s is None else min(lap, self.best_lap_s)
            self.started_us = now_us
            self.checkpoint = 1
            self.valid = on_track


class DrivingSession:
    def __init__(self, start_us=0):
        self.track = Circuit()
        self.x, self.y, self.heading = self.track.pose(0)
        self.segment = 0
        self.progress = 0.0
        self.off_track = False
        self.timer = LapTimer(self.track.length)
        self.timer.started_us = start_us
        self.armed = False
        self.last_input_us = start_us
        self.input_fault = "Jízda připravena. Zvol ovládání a stiskni Pokračovat."
        self.source = "keyboard"
        self.last_time_us = start_us

    def before_step(self, vehicle):
        # Přilnavost obou stran odvozujeme od skutečné polohy kol na vozovce.
        front = vehicle.config.wheelbase_m / 2
        half_track = vehicle.config.track_m / 2
        c, s = math.cos(self.heading), math.sin(self.heading)
        for name, side in (("mu_left", 1), ("mu_right", -1)):
            x = self.x + front * c - side * half_track * s
            y = self.y + front * s + side * half_track * c
            p = self.track.project(x, y, self.segment)
            if p.distance > self.track.width / 2 + 2:
                p = self.track.project(x, y)
            setattr(vehicle, name, 0.85 if p.distance <= self.track.width / 2 else 0.28)
        vehicle.surface_drag_n = 600.0 if self.off_track else 0.0

    def step(self, vehicle, dt, now_us):
        # Kladné stáčení je vlevo; světové y roste nahoru (na Canvas se obrátí).
        middle = self.heading + vehicle.yaw_rate * dt / 2
        self.x += vehicle.speed * math.cos(middle) * dt
        self.y += vehicle.speed * math.sin(middle) * dt
        self.heading += vehicle.yaw_rate * dt
        vehicle.heading = self.heading
        p = self.track.project(self.x, self.y, self.segment)
        if p.distance > self.track.width / 2 + 2:
            p = self.track.project(self.x, self.y)
        self.segment, self.progress = p.segment, p.progress
        self.off_track = p.distance > self.track.width / 2
        self.timer.update(self.progress, now_us, not self.off_track)
        self.last_time_us = now_us

    def snapshot(self):
        return {
            "x_m": self.x,
            "y_m": self.y,
            "heading_rad": self.heading,
            "track": self.track.name,
            "track_length_m": self.track.length,
            "progress_m": self.progress,
            "off_track": self.off_track,
            "laps": self.timer.laps,
            "lap_time_s": (self.last_time_us - self.timer.started_us) / 1e6,
            "last_lap_s": self.timer.last_lap_s,
            "best_lap_s": self.timer.best_lap_s,
            "lap_valid": self.timer.valid,
            "checkpoint": self.timer.checkpoint,
            "armed": self.armed,
            "input_fault": self.input_fault,
            "source": self.source,
        }
