#!/usr/bin/env python3
"""Jediný zdroj konfigurace: JSON → C hlavičky, Wokwi zapojení a pinmapa."""

import argparse
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from hardware_wiring import diagram as build_diagram, drawing


def number(value, low, high):
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or not low <= value <= high
    ):
        raise ValueError(f"number outside {low}..{high}: {value}")
    return value


def integer(value, low, high):
    if type(value) is not int:
        raise ValueError("expected integer")
    return number(value, low, high)


def boolean(value):
    if type(value) is not bool:
        raise ValueError("expected boolean")
    return "true" if value else "false"


def load(engine_path, pinout_path, target=None):
    e = json.loads(Path(engine_path).read_text())
    pins = json.loads(Path(pinout_path).read_text())
    target = target or pins["target"]
    p = pins["profiles"][target]
    for k in ("cylinders", "injectors", "ignition_channels"):
        integer(e[k], 1, 4)
    if e["injectors"] != e["cylinders"] or e["ignition_channels"] != e["cylinders"]:
        raise ValueError("demo requires one injector and ignition per cylinder")
    if sorted(e["firing_order"]) != list(range(1, e["cylinders"] + 1)):
        raise ValueError("invalid firing order")
    c, m = e["ckp"], e["cmp"]
    integer(c["teeth"], 4, 360)
    integer(c["missing"], 1, c["teeth"] - 2)
    number(c["duty"], 0.05, 0.95)
    integer(c["skip_tooth"], -1, c["teeth"] - c["missing"] - 1)
    number(c["noise_angle_deg"], -1, 359.999)
    number(c["noise_width_deg"], 0.01, 10)
    number(m["width_deg"], 0.01, 180)
    number(m["fault_offset_deg"], -720, 720)
    positions = sorted(m["positions_deg"])
    integer(len(positions), 1, 8)
    for a in positions:
        number(a, 0, 719.999)
    if (
        any(
            (positions[(i + 1) % len(positions)] - a) % 720 < m["width_deg"]
            for i, a in enumerate(positions)
        )
        and len(positions) > 1
    ):
        raise ValueError("overlapping CMP pulses")
    for obj, key in (
        (c, "active_high"),
        (m, "active_high"),
        (m, "stuck_inactive"),
        (e["capture"], "injector_active_high"),
        (e["capture"], "ignition_active_high"),
    ):
        boolean(obj[key])
    integer(e["capture"]["max_pulse_us"], 100, 1000000)
    comm = e["communication"]
    integer(comm["baudrate"], 115200, 2000000)
    integer(comm["rfc2217_port"], 1024, 65535)
    integer(comm["diagnostic_baudrate"], 9600, 1000000)
    if (
        not isinstance(comm["host"], str)
        or not comm["host"]
        or any(c in comm["host"] for c in "/?#@:")
    ):
        raise ValueError("invalid RFC2217 hostname")
    integer(comm["lookahead_us"], 1000, 1000000)
    integer(comm["watchdog_us"], 10000, 5000000)
    if comm["queue_capacity"] != 64:
        raise ValueError("compiled bounded queue capacity is 64")
    if comm["mode"] not in ("buffered", "free"):
        raise ValueError("unsupported synchronization mode")
    for k in ("injection_us", "dwell_us"):
        integer(e["demo"][k], 100, 20000)
    number(e["demo"]["advance_deg"], 0, 60)
    integer(e["demo"]["timer_us"], 10, 100)
    used = [p["ckp"], p["cmp"], *p["analog"], *p["injectors"], *p["ignition"]]
    if len(set(used)) != len(used):
        raise ValueError("GPIO overlap")
    if (
        len(p["analog"]) != 5
        or len(p["analog_labels"]) != 5
        or len(p["injectors"]) != 4
        or len(p["ignition"]) != 4
    ):
        raise ValueError("invalid pin counts")
    for pin in used:
        integer(pin, 0, 69 if target == "mega" else 39)
    if target == "esp32":
        if set(used) & {0, 1, 2, 3, 5, 6, 7, 8, 9, 10, 11, 12, 15}:
            raise ValueError("ESP32 reserved/boot/UART GPIO")
        if any(pin >= 34 for pin in [p["ckp"], p["cmp"], *p["injectors"], *p["ignition"]]):
            raise ValueError("ESP32 output/interrupt pin profile unsupported")
    curves = []
    for name in ("MAP", "TPS", "IAT", "CLT", "LAMBDA"):
        sensor = e["analog"][name]
        if "ntc" in sensor:
            n = sensor["ntc"]
            points = []
            for key in ("r25", "beta", "pullup"):
                number(n[key], 1, 1000000)
            number(n["supply_v"], 0.1, 5)
            for t in sensor["temperatures"]:
                number(t, -100, 250)
                r = n["r25"] * math.exp(n["beta"] * (1 / (t + 273.15) - 1 / 298.15))
                points.append([t, n["supply_v"] * r / (n["pullup"] + r)])
        else:
            points = sensor["points"]
        integer(len(points), 2, 16)
        for x, v in points:
            number(x, -1000, 10000)
            number(v, 0, 5)
        if any(a[0] >= b[0] for a, b in zip(points, points[1:])):
            raise ValueError("unordered analog curve")
        curves.append(points)
    pedal_points = e["analog"]["TPS"]["points"]
    if pedal_points[0][1] >= pedal_points[-1][1]:
        raise ValueError("TPS/pedal calibration must have increasing endpoint voltages")
    return e, p, target, curves


def generate(e, p, target, curves):
    c, m, cap = e["ckp"], e["cmp"], e["capture"]
    array = lambda xs: "{" + ",".join(f"{v:.12g}" for v in xs) + "}"
    header = "// Generated by scripts/configure.py; edit config/*.json.\nstatic const hw_config_t HW_CONFIG={\n"
    fields = {
        "cylinders": e["cylinders"],
        "injectors": e["injectors"],
        "ignitions": e["ignition_channels"],
        "teeth": c["teeth"],
        "missing": c["missing"],
        "cmp_count": len(m["positions_deg"]),
        "ckp_high": boolean(c["active_high"]),
        "cmp_high": boolean(m["active_high"]),
        "injector_high": boolean(cap["injector_active_high"]),
        "ignition_high": boolean(cap["ignition_active_high"]),
        "cmp_stuck": boolean(m["stuck_inactive"]),
        "duty": c["duty"],
        "cmp_width": m["width_deg"],
        "cmp_positions": array(m["positions_deg"]),
        "cmp_offset": m["fault_offset_deg"],
        "skip_tooth": c["skip_tooth"],
        "noise_angle": c["noise_angle_deg"],
        "noise_width": c["noise_width_deg"],
        "max_pulse_us": cap["max_pulse_us"],
        "watchdog_us": e["communication"]["watchdog_us"],
    }
    header += "".join(f"  .{k}={v},\n" for k, v in fields.items())
    header += (
        "  .analog={\n"
        + "".join(
            f"    {{.count={len(points)},.x={array([x for x, _ in points])},.v={array([v for _, v in points])}}},\n"
            for points in curves
        )
        + "  }\n};\n"
        + f"#define HW_UART_BAUD {e['communication']['baudrate']}\n#define HW_DIAG_BAUD {e['communication']['diagnostic_baudrate']}\n"
    )
    fw = "// Generated from config/*.json.\n#pragma once\n"
    definitions = {
        "ECU_DIAG_BAUD": e["communication"]["diagnostic_baudrate"],
        "ECU_CYLINDERS": e["cylinders"],
        "ECU_CKP_PIN": p["ckp"],
        "ECU_CMP_PIN": p["cmp"],
        "ECU_TEETH": c["teeth"],
        "ECU_MISSING": c["missing"],
        "ECU_CKP_ACTIVE": int(c["active_high"]),
        "ECU_CMP_ACTIVE": int(m["active_high"]),
        "ECU_CMP_REFERENCE": m["positions_deg"][0],
        "ECU_INJ_ACTIVE": int(cap["injector_active_high"]),
        "ECU_IGN_ACTIVE": int(cap["ignition_active_high"]),
        "ECU_INJECTION_US": e["demo"]["injection_us"],
        "ECU_DWELL_US": e["demo"]["dwell_us"],
        "ECU_ADVANCE_DEG": e["demo"]["advance_deg"],
        "ECU_TIMER_US": e["demo"]["timer_us"],
        "ECU_ADC_REFERENCE_V": 5.0,
        "ECU_PEDAL_MIN_V": e["analog"]["TPS"]["points"][0][1],
        "ECU_PEDAL_MAX_V": e["analog"]["TPS"]["points"][-1][1],
    }
    fw += "".join(f"#define {k} {v}\n" for k, v in definitions.items())
    for name, vals in [
        ("INJECTOR_PINS", p["injectors"]),
        ("IGNITION_PINS", p["ignition"]),
        ("ANALOG_PINS", p["analog"]),
        ("FIRING_ORDER", e["firing_order"]),
    ]:
        fw += f"static const unsigned {name}[]={array(vals)};\n"
    diagram, pinmap = build_diagram(e, p, target)
    extension = "bin" if target == "esp32" else "hex"
    toml = f"""# Generated for {target}; ECU UART is NOT the simulation transport.
[wokwi]
version = 1
firmware = '.pio/build/{target}/firmware.{extension}'
elf = '.pio/build/{target}/firmware.elf'
rfc2217ServerPort = {e["communication"]["rfc2217_port"]}
vcdFile = 'capture.vcd'

[[chip]]
name = 'engine-interface'
binary = 'chips/engine-interface/engine-interface.chip.wasm'

[[chip]]
name = 'sensor-front-end'
binary = 'chips/sensor-front-end/sensor-front-end.chip.wasm'

[[chip]]
name = 'output-stage'
binary = 'chips/output-stage/output-stage.chip.wasm'
"""
    doc = (
        f"# Generovaná pinmapa – {target}\n\n| Custom Chip | ECU pin |\n| --- | --- |\n"
        + "".join(f"| {a} | {b} |\n" for a, b in pinmap)
    )
    doc += "\n![Signálové schéma](wiring.svg)\n"
    doc += "\nSignály snímačů vedou přes sensor-front-end; povely INJ/IGN přes output-stage.\n"
    doc += "\nSerial Monitor TX → chip RX, chip TX → Serial Monitor RX. ECU TX → DIAG_RX (diagnostika).\n"
    wiring = drawing(target, e)
    return {
        "config/generated_hw.h": header,
        "config/generated_outputs.h": (
            "// Generated from config/engine.json.\n#pragma once\n"
            f"#define OUTPUT_CYLINDERS {e['cylinders']}\n"
            f"#define OUTPUT_INJ_ACTIVE {int(cap['injector_active_high'])}\n"
            f"#define OUTPUT_IGN_ACTIVE {int(cap['ignition_active_high'])}\n"
        ),
        "firmware/include/generated_pins.h": fw,
        "diagram.json": json.dumps(diagram, indent=2) + "\n",
        "wokwi.toml": toml,
        "config/PINOUT.md": doc,
        "config/wiring.svg": wiring,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", choices=["esp32", "mega"])
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        files = generate(
            *load(ROOT / "config/engine.json", ROOT / "config/pinout.json", args.target)
        )
    except (ValueError, KeyError, TypeError) as exc:
        parser.error(str(exc))
    dirty = []
    for name, content in files.items():
        path = ROOT / name
        if args.check:
            if not path.exists() or path.read_text() != content:
                dirty.append(name)
        else:
            path.write_text(content)
    if dirty:
        parser.exit(1, "Stale generated files: " + ", ".join(dirty) + "\n")
    print("Hardware configuration: OK")


if __name__ == "__main__":
    main()
