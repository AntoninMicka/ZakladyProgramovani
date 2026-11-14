#!/usr/bin/env python3
"""Jediný zdroj konfigurace: JSON → C hlavičky, Wokwi zapojení a pinmapa."""

import argparse
import json
import math
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


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
    }
    fw += "".join(f"#define {k} {v}\n" for k, v in definitions.items())
    for name, vals in [
        ("INJECTOR_PINS", p["injectors"]),
        ("IGNITION_PINS", p["ignition"]),
        ("ANALOG_PINS", p["analog"]),
        ("FIRING_ORDER", e["firing_order"]),
    ]:
        fw += f"static const unsigned {name}[]={array(vals)};\n"
    parts = [
        dict(type=p["part"], id="ecu", left=0, top=0, attrs={}),
        dict(type="chip-engine-interface", id="engine", left=500, top=0, attrs={}),
        dict(type="wokwi-logic-analyzer", id="logic", left=500, top=-220, attrs={}),
    ]
    connections = [
        ["$serialMonitor:TX", "engine:RX", "green", []],
        ["engine:TX", "$serialMonitor:RX", "green", []],
        [f"ecu:{p['power']}", "engine:VCC", "red", []],
        [f"ecu:{p['ground']}", "engine:GND", "black", []],
        [f"ecu:{p['diagnostic_tx']}", "engine:DIAG_RX", "gray", []],
    ]
    pinmap = []

    def connect(gpio, chip, color):
        label = p.get("digital_labels", {}).get(str(gpio), f"{p['digital_prefix']}{gpio}")
        connections.append([f"ecu:{label}", f"engine:{chip}", color, []])
        pinmap.append((chip, label))

    connect(p["ckp"], "CKP", "blue")
    connect(p["cmp"], "CMP", "purple")
    for i, name in enumerate(("MAP", "TPS", "IAT", "CLT", "LAMBDA")):
        connections.append([f"engine:{name}", f"ecu:{p['analog_labels'][i]}", "orange", []])
        pinmap.append((name, p["analog_labels"][i]))
    for i in range(4):
        connect(p["injectors"][i], f"INJ{i + 1}", "green")
        connect(p["ignition"][i], f"IGN{i + 1}", "magenta")
    for i, name in enumerate(("CKP", "CMP", "INJ1", "IGN1")):
        connections.append([f"engine:{name}", f"logic:D{i}", "blue", []])
    connections.append(["logic:GND", "engine:GND", "black", []])
    diagram = dict(
        version=1,
        author="ECU Hardware Simulator",
        editor="wokwi",
        parts=parts,
        connections=connections,
        serialMonitor=dict(display="always", newline="lf"),
    )
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
"""
    doc = (
        f"# Generovaná pinmapa – {target}\n\n| Custom Chip | ECU pin |\n| --- | --- |\n"
        + "".join(f"| {a} | {b} |\n" for a, b in pinmap)
    )
    doc += "\n![Signálové schéma](wiring.svg)\n"
    doc += "\nSerial Monitor TX → chip RX, chip TX → Serial Monitor RX. ECU TX → DIAG_RX (diagnostika).\n"
    svg = [
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1100 940" role="img" aria-labelledby="title desc">',
        '<title id="title">ECU Hardware Simulator – izolované simulační rozhraní</title>',
        '<desc id="desc">Python komunikuje přímo s UART adaptérem chipu přes explicitní piny Serial Monitoru. ECU firmware používá pouze CKP, CMP, analogové snímače a výstupy INJ/IGN.</desc>',
        '<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M0 0 L10 5 L0 10 Z" fill="context-stroke"/></marker></defs>',
        '<rect width="1100" height="940" fill="#0f172a"/>',
        '<g font-family="DejaVu Sans,Arial,sans-serif" fill="#e2e8f0">',
        '<text x="35" y="42" font-size="24">ECU Hardware Simulator · ' + escape(target) + "</text>",
        '<rect x="35" y="70" width="1030" height="105" rx="10" fill="#1e293b" stroke="#38bdf8"/>',
        '<text x="55" y="102" font-size="17">Python model ↔ RFC2217 / Serial Monitor ↔ UART adaptér v Custom Chipu</text>',
        '<text x="55" y="130" font-size="14">JSON Lines + CRC32 · relace · buffered segmenty · virtuální čas Wokwi</text>',
        '<text x="55" y="155" font-size="14" fill="#fbbf24">Přímá topologie UART čeká na skutečný integrační test Wokwi.</text>',
        '<path d="M900 175 V205" stroke="#38bdf8" stroke-width="2" marker-start="url(#arrow)" marker-end="url(#arrow)"/>',
        '<rect x="35" y="210" width="300" height="545" rx="10" fill="#1e293b" stroke="#64748b"/>',
        '<rect x="755" y="210" width="310" height="545" rx="10" fill="#1e293b" stroke="#64748b"/>',
        '<text x="55" y="241" font-size="18">ECU MCU · pouze GPIO / ADC</text>',
        '<text x="775" y="241" font-size="18">Engine Interface Custom Chip</text>',
    ]
    for i, (name, label) in enumerate(pinmap):
        y = 278 + i * 27
        output = name.startswith(("INJ", "IGN"))
        color = "#4ade80" if output else "#38bdf8"
        svg.append(
            f'<text x="315" y="{y + 5}" text-anchor="end" font-size="15">{escape(label)}</text>'
        )
        svg.append(
            f'<path d="M335 {y} H755" stroke="{color}" stroke-width="2" marker-{"end" if output else "start"}="url(#arrow)"/>'
        )
        svg.append(f'<text x="775" y="{y + 5}" font-size="15">{escape(name)}</text>')
    svg.extend(
        [
            '<text x="55" y="727" font-size="13">TX → DIAG_RX → Chips Console</text>',
            '<text x="775" y="727" font-size="13">VCC / GND společné s MCU</text>',
            '<rect x="35" y="785" width="1030" height="75" rx="10" fill="#1e293b" stroke="#a78bfa"/>',
            '<text x="55" y="814" font-size="17">Logic Analyzer: D0 ← CKP · D1 ← CMP · D2 ← INJ1 · D3 ← IGN1</text>',
            '<text x="55" y="840" font-size="14">Export VCD → kontrola geometrie a časování · samostatně od UART diagnostiky</text>',
            '<text x="35" y="900" font-size="14" fill="#94a3b8">Firmware ECU neobsahuje simulační JSON protokol ani fyzikální model motoru.</text>',
            "</g></svg>",
        ]
    )
    wiring = "\n".join(svg) + "\n"
    return {
        "config/generated_hw.h": header,
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
