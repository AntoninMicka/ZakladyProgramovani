"""Společný textový výpis a omezený archiv vzorků pro GUI."""

from collections import deque
import json


def format_sample(state, bridge, wall_elapsed_s):
    link = bridge.get("connected", "mock")
    if isinstance(link, bool):
        link = "online" if link else "offline"
    diagnostic = state["diagnostics"]
    levels = state["signal_levels"]
    text = (
        f"wall={wall_elapsed_s:8.3f}s sim={state['time_s']:9.4f}s "
        f"RPM={state['rpm']:7.1f} TPS={state['tps'] * 100:5.1f}% "
        f"MAP={state['map_kpa']:5.1f}kPa λ={state['lambda_value']:.2f} "
        f"inj={state['injector_ms']:5.2f}ms spark={state['ignition_deg']:5.1f}° "
        f"load={state['load_nm']:5.1f}Nm crank={state['crank_angle_deg']:6.1f}° "
        f"cycle={state['cycle_angle_deg']:6.1f}° "
        f"CKP/CMP={levels['CKP']}/{levels['CMP']} link={link} "
        f"lost={diagnostic['dropped_events']} late={diagnostic['late_events']} "
        f"rejected={diagnostic['rejected_commands']}"
    )
    controller = bridge.get("controller")
    if controller:
        goal = controller.get("requested_rpm")
        text += (
            f" ECU_pedal={controller.get('accelerator', 0) * 100:.1f}%"
            f" ECU_fuel={controller.get('injection_us', 0)}us"
            f" ECU_rpm_goal={goal if goal is not None else 'off'}"
        )
    vehicle = state.get("vehicle")
    if vehicle:
        text += (f" CAR={vehicle['speed_kmh']:.1f}km/h gear={vehicle['gear']}"
                 f" ABS={vehicle['abs_active']} ESP={vehicle['esp_active']}"
                 f" CAN={vehicle['can']['delivered']}/{vehicle['can']['dropped']}")
    hardware = bridge.get("hardware")
    if hardware:
        text += (
            f" hw_run={hardware['running']} hw_queue={hardware['queue_depth']}"
            f" hw_late={hardware['late_updates']} hw_crc={hardware['crc_errors']}"
        )
    return text


def serialize_record(state, bridge, wall_elapsed_s):
    """Jeden neměnný JSONL vzorek pro soubor i paměťovou historii."""
    return json.dumps(
        {"wall_elapsed_s": wall_elapsed_s, "state": state, "bridge": bridge},
        ensure_ascii=False,
        allow_nan=False,
    )


class TelemetryBuffer:
    def __init__(self, capacity=1000):
        if not isinstance(capacity, int) or capacity <= 0:
            raise ValueError("telemetry capacity must be positive")
        self.samples = deque(maxlen=capacity)
        self.total = 0

    def append(self, state, bridge, wall_elapsed_s):
        # Serializace vytvoří nezávislý snímek i pro vnořené diagnostické hodnoty.
        raw = serialize_record(state, bridge, wall_elapsed_s)
        line = format_sample(state, bridge, wall_elapsed_s)
        self.samples.append((raw, line))
        self.total += 1
        return line

    def clear(self):
        self.samples.clear()
        self.total = 0

    def jsonl(self):
        return "".join(raw + "\n" for raw, _ in self.samples)

    def text(self):
        return "".join(line + "\n" for _, line in self.samples)
