"""Perspektivní pohled z čelního okna nad skutečnou polohou modelu.

Lehký 2,5D renderer na Tk Canvas: rovinná vozovka, procedurální krajina a kokpit.
Nemění fyziku ani vstupní zařízení; nepoužívá druhý model pohybu auta.
"""

import math

from racetrack import Circuit


def clip_near(points, near=2.0):
    """Ořízne polygon v souřadnicích (boční vzdálenost, hloubka) před kamerou."""
    result = []
    for a, b in zip(points, points[1:] + points[:1]):
        inside_a, inside_b = a[1] >= near, b[1] >= near
        if inside_a:
            result.append(a)
        if inside_a != inside_b:
            t = (near - a[1]) / (b[1] - a[1])
            result.append((a[0] + t * (b[0] - a[0]), near))
    return result


class CockpitView:
    def __init__(self, canvas, track=None):
        self.canvas = canvas
        self.track = track or Circuit()
        self.edges = []
        self.scenery = []
        points = self.track.points
        for i, point in enumerate(points):
            before, after = points[(i - 1) % len(points)], points[(i + 1) % len(points)]
            dx, dy = after[0] - before[0], after[1] - before[1]
            length = math.hypot(dx, dy)
            nx, ny = -dy / length, dx / length
            self.edges.append((point, nx, ny))
            if i % 4 == 0:
                for side in (-1, 1):
                    offset = side * (25 + (i % 7) * 3)
                    x, y = point[0] + nx * offset, point[1] + ny * offset
                    if self.track.project(x, y).distance > self.track.width:
                        self.scenery.append((x, y, "tree" if i % 12 else "house", 6 + i % 5))

    @staticmethod
    def camera_point(x, y, car_x, car_y, heading):
        dx, dy = x - car_x, y - car_y
        return dx * math.sin(heading) - dy * math.cos(heading), dx * math.cos(
            heading
        ) + dy * math.sin(heading)

    def draw(self, state, width, height):
        c = self.canvas
        c.delete("all")
        race = state.get("driving")
        car_x, car_y, heading = (
            (race["x_m"], race["y_m"], race["heading_rad"]) if race else self.track.pose(0)
        )
        horizon = height * 0.36
        focal = width * 0.75
        camera_height = 1.15

        def world(x, y):
            return self.camera_point(x, y, car_x, car_y, heading)

        def project(lateral, depth, altitude=0):
            return width / 2 + lateral * focal / depth, horizon + (
                camera_height - altitude
            ) * focal / depth

        def road_polygon(world_points, color, tag):
            points = clip_near([world(*p) for p in world_points])
            if len(points) < 3 or min(p[1] for p in points) > 450:
                return None
            coords = [n for p in points for n in project(*p)]
            return coords, color, tag, sum(p[1] for p in points) / len(points)

        # Obloha a vzdálené kopce jsou dekorace, ne překážky či výškový model.
        c.create_rectangle(0, 0, width, height, fill="#93c5e8", outline="", tags="cockpit:sky")
        c.create_oval(
            width * 0.78,
            height * 0.06,
            width * 0.84,
            height * 0.06 + width * 0.06,
            fill="#fef3c7",
            outline="",
        )
        for layer, color in ((0, "#769c95"), (1, "#497d79")):
            ridge = [0, horizon]
            for i in range(25):
                x = width * i / 24
                peak = (
                    horizon
                    - 18
                    - layer * 9
                    - abs(math.sin(i * 0.63 + heading + layer)) * height * 0.10
                )
                ridge.extend((x, peak))
            ridge.extend((width, horizon))
            c.create_polygon(*ridge, fill=color, outline="", tags="cockpit:landscape")
        c.create_rectangle(
            0, horizon, width, height, fill="#608441", outline="", tags="cockpit:grass"
        )
        for i in range(5):
            y = horizon + (height * 0.39) * (i / 5) ** 2
            c.create_rectangle(0, y, width, y + max(2, i * 3), fill="#668c47", outline="")
        # Vozovka i krajnice se promítají z téže geometrie jako mapa a fyzika.
        polygons = []
        for i, (a, nx, ny) in enumerate(self.edges):
            b, bnx, bny = self.edges[(i + 1) % len(self.edges)]
            half = self.track.width / 2

            def strip(inner, outer, a=a, b=b, nx=nx, ny=ny, bnx=bnx, bny=bny):
                return [
                    (a[0] + nx * inner, a[1] + ny * inner),
                    (b[0] + bnx * inner, b[1] + bny * inner),
                    (b[0] + bnx * outer, b[1] + bny * outer),
                    (a[0] + nx * outer, a[1] + ny * outer),
                ]

            for pts, color, tag in (
                (strip(-half, half), "#414953", "cockpit:road"),
                (strip(half, half + 1), "#f8fafc" if i % 2 else "#c94d47", "cockpit:kerb"),
                (strip(-half - 1, -half), "#f8fafc" if i % 2 else "#c94d47", "cockpit:kerb"),
            ):
                p = road_polygon(pts, color, tag)
                if p:
                    polygons.append(p)
            if i % 3 == 0:
                p = road_polygon(strip(-0.10, 0.10), "#d1d5db", "cockpit:lane")
                if p:
                    polygons.append(p)
        for coords, color, tag, _ in sorted(polygons, key=lambda p: p[3], reverse=True):
            c.create_polygon(*coords, fill=color, outline="", tags=tag)
        # Stromy a malé budovy stojí v pevných světových bodech mimo asfalt.
        objects = []
        for x, y, kind, size in self.scenery:
            lateral, depth = world(x, y)
            if 4 < depth < 300:
                sx, sy = project(lateral, depth)
                if -100 < sx < width + 100:
                    objects.append((depth, sx, sy, kind, size * focal / depth))
        for _, sx, sy, kind, size in sorted(objects, reverse=True):
            if kind == "tree":
                c.create_rectangle(
                    sx - size * 0.08,
                    sy - size * 0.8,
                    sx + size * 0.08,
                    sy,
                    fill="#67503a",
                    outline="",
                )
                c.create_polygon(
                    sx - size * 0.42,
                    sy - size * 0.35,
                    sx,
                    sy - size * 1.3,
                    sx + size * 0.42,
                    sy - size * 0.35,
                    fill="#285b3c",
                    outline="#244f35",
                    tags="cockpit:tree",
                )
            else:
                c.create_rectangle(
                    sx - size * 0.6,
                    sy - size * 0.7,
                    sx + size * 0.6,
                    sy,
                    fill="#d7c5a3",
                    outline="#8c795e",
                    tags="cockpit:house",
                )
                c.create_polygon(
                    sx - size * 0.75,
                    sy - size * 0.7,
                    sx,
                    sy - size * 1.1,
                    sx + size * 0.75,
                    sy - size * 0.7,
                    fill="#9e574a",
                    outline="",
                )
                c.create_rectangle(
                    sx - size * 0.15,
                    sy - size * 0.35,
                    sx + size * 0.15,
                    sy,
                    fill="#5b6c70",
                    outline="",
                )
        # Kapota, A-sloupky a přístrojová deska ohraničují čelní sklo.
        c.create_polygon(
            0,
            height * 0.74,
            width * 0.15,
            height * 0.66,
            width * 0.85,
            height * 0.66,
            width,
            height * 0.74,
            width,
            height,
            0,
            height,
            fill="#17202b",
            outline="#64748b",
            width=3,
            tags="cockpit:dashboard",
        )
        c.create_polygon(
            0,
            0,
            width * 0.035,
            0,
            width * 0.13,
            height * 0.69,
            0,
            height * 0.77,
            fill="#202b36",
            outline="",
        )
        c.create_polygon(
            width,
            0,
            width * 0.965,
            0,
            width * 0.87,
            height * 0.69,
            width,
            height * 0.77,
            fill="#202b36",
            outline="",
        )
        c.create_line(
            width * 0.13, height * 0.69, width * 0.87, height * 0.69, fill="#94a3b8", width=3
        )
        v = state.get("vehicle", {})
        d = v.get("dashboard", {})
        self.gauge(
            width * 0.43, height * 0.78, height * 0.075, d.get("rpm"), 7500, "ot/min", "#4ade80"
        )
        self.gauge(
            width * 0.57, height * 0.78, height * 0.075, d.get("speed_kmh"), 180, "km/h", "#38bdf8"
        )
        gear = d.get("gear")
        gear_text = "—" if gear is None else "R" if gear == -1 else "N" if gear == 0 else str(gear)
        c.create_text(
            width * 0.73,
            height * 0.79,
            text=f"PŘEVOD {gear_text}",
            fill="#e2e8f0",
            font=("Sans", 15, "bold"),
        )
        lamps = (
            ("ABS", d.get("abs", False)),
            ("ESP", d.get("esp", False)),
            ("CAN", d.get("can_fault", True)),
        )
        for i, (label, on) in enumerate(lamps):
            c.create_text(
                width * 0.62 + i * width * 0.065,
                height * 0.85,
                text=label,
                fill="#fbbf24" if on else "#64748b",
                font=("Sans", 11, "bold"),
            )

        def number(value, unit):
            return "—" if value is None else f"{value:.0f} {unit}"

        c.create_text(
            width * 0.70,
            height * 0.92,
            text=f"Palivo {number(d.get('fuel_pct'), '%')} · {number(d.get('coolant_c'), '°C')}",
            fill="#94a3b8",
            font=("Sans", 10),
        )
        for i in range(5):
            x = width * 0.80 + i * width * 0.018
            c.create_line(
                x, height * 0.75, x - width * 0.008, height * 0.80, fill="#475569", width=3
            )
        # Volant má přímou vazbu na aktuální natočení řízení, ne na směr kamery.
        cx, cy, r = width * 0.29, height * 0.91, height * 0.15
        angle = -math.radians(v.get("steer_deg", 0) * 14)
        c.create_oval(
            cx - r,
            cy - r,
            cx + r,
            cy + r,
            fill="",
            outline="#0a1018",
            width=max(10, r * 0.16),
            tags="cockpit:wheel",
        )
        c.create_oval(
            cx - r * 0.91,
            cy - r * 0.91,
            cx + r * 0.91,
            cy + r * 0.91,
            fill="",
            outline="#475569",
            width=2,
        )
        for spoke in (0, 2.1, 4.2):
            theta = angle + spoke
            c.create_line(
                cx,
                cy,
                cx + math.cos(theta) * r * 0.9,
                cy + math.sin(theta) * r * 0.9,
                fill="#6b7888",
                width=max(5, r * 0.12),
                tags="cockpit:spoke",
            )
        c.create_oval(
            cx - r * 0.3,
            cy - r * 0.3,
            cx + r * 0.3,
            cy + r * 0.3,
            fill="#1e293b",
            outline="#64748b",
            width=2,
        )
        c.create_text(cx, cy, text="ECU", fill="#cbd5e1", font=("Sans", 12, "bold"))
        # Malé pedálové ukazatele dovolují rychle ověřit mapování ovladače.
        for i, (label, value, color) in enumerate(
            (("PLYN", state.get("throttle", 0), "#4ade80"), ("BRZDA", v.get("brake", 0), "#fb923c"))
        ):
            x = width * 0.05 + i * width * 0.09
            c.create_rectangle(
                x,
                height * 0.88,
                x + width * 0.045,
                height * 0.96,
                fill="#0f172a",
                outline="#475569",
            )
            c.create_rectangle(
                x,
                height * 0.96 - value * height * 0.08,
                x + width * 0.045,
                height * 0.96,
                fill=color,
                outline="",
            )
            c.create_text(
                x + width * 0.022, height * 0.975, text=label, fill="#94a3b8", font=("Sans", 8)
            )
        if race:
            best = "—" if race["best_lap_s"] is None else f"{race['best_lap_s']:.2f} s"
            text = f"Kolo {race['laps'] + 1} · {race['lap_time_s']:.2f} s · nejlepší {best}"
            if not race["lap_valid"]:
                text += " · NEPLATNÉ (mimo trať)"
        else:
            text = "Zapni jízdu a potvrď pokračování · joypad / šipky"
        c.create_rectangle(width * 0.05, 8, width * 0.95, 40, fill="#17202b", outline="")
        c.create_text(
            width / 2, 24, text=text, fill="#e2e8f0", font=("Sans", 12, "bold"), tags="cockpit:lap"
        )
        if state.get("paused", False):
            c.create_text(
                width / 2,
                height * 0.53,
                text="POZASTAVENO · Pokračovat",
                fill="#fef3c7",
                font=("Sans", 19, "bold"),
                tags="cockpit:paused",
            )

    def gauge(self, cx, cy, r, value, maximum, label, color):
        c = self.canvas
        c.create_oval(cx - r, cy - r, cx + r, cy + r, fill="#09121c", outline="#64748b", width=2)
        for i in range(9):
            angle = math.radians(210 - i * 30)
            c.create_line(
                cx + math.cos(angle) * r * 0.78,
                cy - math.sin(angle) * r * 0.78,
                cx + math.cos(angle) * r * 0.9,
                cy - math.sin(angle) * r * 0.9,
                fill="#94a3b8",
                width=1,
            )
        if value is not None:
            angle = math.radians(210 - max(0, min(1, value / maximum)) * 240)
            c.create_line(
                cx,
                cy,
                cx + math.cos(angle) * r * 0.72,
                cy - math.sin(angle) * r * 0.72,
                fill=color,
                width=3,
            )
        c.create_text(
            cx,
            cy + r * 0.38,
            text="—" if value is None else f"{value:.0f}",
            fill="#e2e8f0",
            font=("Sans", max(9, int(r * 0.29)), "bold"),
        )
        c.create_text(cx, cy - r * 0.35, text=label, fill="#94a3b8", font=("Sans", 9))
