"""Čistá geometrie pro názorný pohled, bez závislosti na Tk a modelu."""
import math


def cylinder_phase(cycle_angle, channel, cylinders):
    """Pořadí zážehů pro čtyřválec 1–3–4–2, jinak rovnoměrné pořadí kanálů."""
    offset = (0, 540, 180, 360)[channel] if cylinders == 4 else channel * 720 / cylinders
    return (cycle_angle + 360 - offset) % 720


def piston_position(angle, rod_ratio=3.5):
    """Normovaný zdvih 0=HÚ, 1=DÚ, z geometrie kliky a ojnice."""
    radians = math.radians(angle)
    height = math.cos(radians) + math.sqrt(rod_ratio**2 - math.sin(radians)**2)
    return (1 + rod_ratio - height) / 2


