"""Stejný C++ EcuController jako ve firmware, načtený přes malé rozhraní ctypes."""

import ctypes as c
import hashlib
import json
import math
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT / "wokwi/hardware"


class InputEdge(c.Structure):
    _fields_ = [("time", c.c_uint64), ("signal", c.c_uint32), ("level", c.c_uint32)]


class OutputEdge(c.Structure):
    _fields_ = [
        ("time", c.c_uint64),
        ("duration", c.c_uint64),
        ("kind", c.c_uint32),
        ("channel", c.c_uint32),
        ("active", c.c_uint32),
        ("advance", c.c_double),
    ]


def build_native(config, signals, project=PROJECT):
    """Kopie hlavičky je byte-for-byte stejná; vedle ní vznikne konfigurace pro hostitele."""
    project = Path(project)
    controller = (project / "firmware/include/ecu_controller.h").read_bytes()
    demo = json.loads((project / "config/engine.json").read_text())["demo"]
    if signals.missing < 1:
        raise ValueError("Sdílená demo ECU potřebuje kolo s chybějícím zubem.")
    for key in ("injection_us", "dwell_us", "timer_us"):
        value = demo[key]
        if type(value) is not int or not 1 <= value <= 1000000:
            raise ValueError("Neplatná konfigurace Mock ECU: " + key)
    order = [1, 3, 4, 2] if config.cylinders == 4 else list(range(1, config.cylinders + 1))
    settings = json.loads((project / "config/engine.json").read_text())
    if settings["cylinders"] == config.cylinders:
        order = settings["firing_order"]
    if sorted(order) != list(range(1, config.cylinders + 1)):
        raise ValueError("Neplatné pořadí válců Mock ECU")
    if (
        not isinstance(demo["advance_deg"], (int, float))
        or not math.isfinite(demo["advance_deg"])
        or not -180 <= demo["advance_deg"] <= 180
    ):
        raise ValueError("Neplatný předstih Mock ECU")
    values = dict(
        ECU_CYLINDERS=config.cylinders,
        ECU_TEETH=signals.teeth,
        ECU_MISSING=signals.missing,
        ECU_CMP_REFERENCE=signals.cmp_positions[0],
        ECU_INJ_ACTIVE=1,
        ECU_IGN_ACTIVE=1,
        ECU_INJECTION_US=demo["injection_us"],
        ECU_DWELL_US=demo["dwell_us"],
        ECU_ADVANCE_DEG=demo["advance_deg"],
        ECU_TIMER_US=demo["timer_us"],
        ECU_ADC_REFERENCE_V=5.0,
        ECU_PEDAL_MIN_V=settings["analog"]["TPS"]["points"][0][1],
        ECU_PEDAL_MAX_V=settings["analog"]["TPS"]["points"][-1][1],
    )
    header = "#pragma once\n" + "".join(f"#define {key} {value}\n" for key, value in values.items())
    header += "static const unsigned FIRING_ORDER[]={" + ",".join(map(str, order)) + "};\n"
    wrapper = (ROOT / "native/ecu_host.cpp").read_bytes()
    revision = hashlib.sha256(controller + header.encode() + wrapper).hexdigest()
    cache = ROOT / ".cache/native-ecu"
    target = cache / revision / "ecu.so"
    if not target.is_file():
        compiler = shutil.which("g++") or shutil.which("clang++")
        if not compiler:
            raise RuntimeError("Mock ECU vyžaduje C++ překladač: nainstalujte g++ nebo clang++.")
        cache.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=cache) as directory:
            stage = Path(directory)
            (stage / "ecu_controller.h").write_bytes(controller)
            (stage / "generated_pins.h").write_text(header)
            (stage / "ecu_host.cpp").write_bytes(wrapper)
            result = subprocess.run(
                [
                    compiler,
                    "-std=c++17",
                    "-O2",
                    "-shared",
                    "-fPIC",
                    "-Wall",
                    "-Wextra",
                    "-Werror",
                    str(stage / "ecu_host.cpp"),
                    "-o",
                    str(stage / "ecu.so"),
                ],
                capture_output=True,
                text=True,
                timeout=45,
            )
            if result.returncode:
                raise RuntimeError("Překlad Mock ECU selhal:\n" + result.stderr[-12000:])
            target.parent.mkdir(parents=True, exist_ok=True)
            (stage / "ecu.so").replace(target)
    return target, revision


class NativeEcu:
    def __init__(self, config, signals, project=PROJECT):
        path, self.revision = build_native(config, signals, project)
        self.library = lib = c.CDLL(str(path))
        lib.ecu_create.restype = c.c_void_p
        lib.ecu_destroy.argtypes = [c.c_void_p]
        lib.ecu_reset.argtypes = [c.c_void_p, c.c_uint64, c.c_double]
        lib.ecu_advance.argtypes = [
            c.c_void_p,
            c.c_uint64,
            c.c_double,
            c.POINTER(InputEdge),
            c.c_size_t,
            c.POINTER(OutputEdge),
            c.c_size_t,
        ]
        lib.ecu_advance.restype = c.c_int
        for name, kind in (
            ("rpm", c.c_double),
            ("synced", c.c_uint),
            ("errors", c.c_uint32),
            ("pedal", c.c_double),
            ("requested_rpm", c.c_double),
            ("injection_us", c.c_uint32),
        ):
            function = getattr(lib, "ecu_" + name)
            function.argtypes = [c.c_void_p]
            function.restype = kind
        self.handle = lib.ecu_create()
        if not self.handle:
            raise MemoryError("Nelze vytvořit Mock ECU")
        self.outputs = (OutputEdge * 4096)()
        self.received = 0

    def reset(self, now=0, accelerator=1):
        self.library.ecu_reset(self.handle, now, accelerator)
        self.received = 0

    def advance(self, end, edges, accelerator=1):
        inputs = (InputEdge * len(edges))(
            *(InputEdge(e.simulation_time_us, int(e.signal == "CMP"), e.level) for e in edges)
        )
        count = self.library.ecu_advance(
            self.handle, end, accelerator, inputs, len(inputs), self.outputs, len(self.outputs)
        )
        if count < 0:
            raise RuntimeError("Mock ECU: neplatné časy nebo přeplněná fronta výstupů")
        self.received += count
        events = [
            dict(
                simulation_time_us=e.time,
                duration_us=e.duration,
                signal="ignition" if e.kind else "injector",
                channel=e.channel,
                action=(
                    ("charge" if e.active else "spark")
                    if e.kind
                    else ("start" if e.active else "end")
                ),
            )
            for e in self.outputs[:count]
        ]
        for event, output in zip(events, self.outputs[:count]):
            if event["action"] == "spark" and abs(output.advance) <= 180:
                event["ignition_deg"] = output.advance
        return events

    def diagnostics(self):
        if not self.handle:
            return self.last_diagnostics
        return dict(
            revision=self.revision,
            rpm=self.library.ecu_rpm(self.handle),
            synced=bool(self.library.ecu_synced(self.handle)),
            errors=self.library.ecu_errors(self.handle),
            events=self.received,
            accelerator=self.library.ecu_pedal(self.handle),
            requested_rpm=(
                None
                if self.library.ecu_requested_rpm(self.handle) < 0
                else self.library.ecu_requested_rpm(self.handle)
            ),
            injection_us=self.library.ecu_injection_us(self.handle),
        )

    def __del__(self):
        if getattr(self, "handle", None):
            self.close()

    def close(self):
        if self.handle:
            self.last_diagnostics = self.diagnostics()
            self.library.ecu_destroy(self.handle)
            self.handle = None
