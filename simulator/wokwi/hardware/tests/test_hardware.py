"""Nativní integrační prototyp: stejné C jádro/adaptér a C++ logika jako ve WASM/MCU."""

import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parents[1]))
from engine import Engine
from protocol import message, encode, decode, expand_events
from bridge import RFC2217Bridge

spec = importlib.util.spec_from_file_location("hw_configure", ROOT / "scripts/configure.py")
configure = importlib.util.module_from_spec(spec)
spec.loader.exec_module(configure)


class HardwareTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="ecu-hardware-tests-")
        cls.addClassCleanup(cls.temp.cleanup)
        cls.build = Path(cls.temp.name)
        cc = next(
            (shutil.which(name) for name in ("clang", "clang-21", "gcc") if shutil.which(name)),
            None,
        )
        cxx = next(
            (shutil.which(name) for name in ("clang++", "clang++-21", "g++") if shutil.which(name)),
            None,
        )
        if not cc or not cxx:
            raise RuntimeError("C and C++ compiler required")
        common = [cc, "-std=c11", "-Wall", "-Wextra", "-Werror"]
        chip = ROOT / "chips/engine-interface"

        def run(args):
            subprocess.run([str(a) for a in args], check=True, capture_output=True, text=True)

        cls.throughput = cls.build / "throughput-test"
        run(
            [
                *common,
                ROOT / "tests/throughput_test.c",
                chip / "hw_core.c",
                chip / "adapter.c",
                chip / "json.c",
                "-lm",
                "-o",
                cls.throughput,
            ]
        )
        cls.runner = cls.build / "adapter-runner"
        cls.core = cls.build / "core-test"
        cls.controller = cls.build / "controller-test"
        run(
            [
                *common,
                ROOT / "tests/adapter_runner.c",
                chip / "hw_core.c",
                chip / "adapter.c",
                chip / "json.c",
                "-lm",
                "-o",
                cls.runner,
            ]
        )
        run(
            [
                *common,
                ROOT / "tests/core_test.c",
                chip / "hw_core.c",
                "-lm",
                "-o",
                cls.core,
            ]
        )
        run([*common, "-c", chip / "hw_core.c", "-o", cls.build / "core.o"])
        run([*common, "-c", ROOT / "tests/host_config.c", "-o", cls.build / "config.o"])
        run(
            [
                cxx,
                "-std=c++17",
                "-Wall",
                "-Wextra",
                "-Werror",
                "-I",
                ROOT / "firmware/include",
                ROOT / "tests/controller_test.cpp",
                cls.build / "core.o",
                cls.build / "config.o",
                "-lm",
                "-o",
                cls.controller,
            ]
        )

    def frame(self, sequence=1, time=0, session=42, **values):
        data = Engine().snapshot()
        data.update(values)
        data["hardware"] = {
            "session": session,
            "mode": "buffered",
            "lookahead_us": 100000,
        }
        return encode(message("engine_state", sequence, time, data), integrity=True)

    def native(self, raw):
        result = subprocess.run([self.runner], input=raw, capture_output=True, check=True)
        return [decode(line) for line in result.stdout.splitlines()]

    def test_uart_throughput_at_acceptance_and_max_rpm(self):
        result = subprocess.run([self.throughput], capture_output=True, text=True, check=True)
        self.assertIn("PASS 2000 RPM", result.stdout)
        self.assertIn("PASS 7500 RPM", result.stdout)
        print(result.stdout, end="")

    def test_core_virtual_time_scenarios(self):
        result = subprocess.run([self.core], capture_output=True, text=True, check=True)
        self.assertEqual(result.stdout.count("PASS"), 8)

    def test_gpio_firmware_integration(self):
        result = subprocess.run([self.controller], capture_output=True, text=True, check=True)
        self.assertIn("4 sequential injectors", result.stdout)
        self.assertIn("ECU output shutdown", result.stdout)

    def test_crc_protects_envelope_and_values(self):
        raw = self.frame()
        self.assertEqual(decode(raw)["sequence"], 1)
        for altered in (
            raw.replace(b'"sequence":1', b'"sequence":2'),
            raw.replace(b"900.0", b"901.0"),
        ):
            with self.assertRaises(ValueError):
                decode(altered)
            status = self.native(altered + b"STATUS\n")[-1]["data"]
            self.assertEqual(status["received"], 0)
            self.assertEqual(status["crc_errors"], 1)

    def test_native_event_timestamps_and_dwell(self):
        rows = self.native(
            self.frame()
            + b"TIME 110000\nPIN 0 0 1\nPIN 1 2 1\nTIME 112000\nPIN 1 2 0\nTIME 113500\nPIN 0 0 0\n"
        )
        events = [e["data"] for r in rows for e in expand_events(r) if e["type"] == "ecu_event"]
        self.assertEqual(events[0]["simulation_time_us"], 10000)
        self.assertEqual(events[-1]["duration_us"], 3500)
        spark = next(e for e in events if e["action"] == "spark")
        self.assertEqual(spark["duration_us"], 2000)
        self.assertEqual(spark["channel_name"], "IGN3")
        self.assertGreater(spark["crank_angle_deg"], 0)

    def test_python_bridge_to_native_chip_and_back(self):
        engine = Engine()
        bridge = RFC2217Bridge(engine, "unused", hardware=True)
        bridge.worker.connected.set()
        bridge.tick()
        raw = bridge.worker.outgoing.get_nowait()
        self.assertIn("integrity", decode(raw))
        rows = self.native(raw + b"TIME 110000\nPIN 0 0 1\nTIME 113500\nPIN 0 0 0\nSTATUS\n")
        for row in rows:
            bridge._receive_bytes(encode(row))
        for _ in range(15):
            engine.step()
        self.assertEqual(engine.model.last_injection_us, {0: 3500})
        self.assertTrue(bridge.metrics["hardware"]["running"])
        self.assertEqual(bridge.metrics["invalid"], 0)
        bridge.close()

    def test_malformed_range_and_unprotected_messages(self):
        rows = self.native(
            b"bad-json\n"
            + b"x" * 17000
            + b"\n"
            + self.frame(rpm=30000)
            + self.frame()[:-1].replace(b',"integrity":', b',"x-integrity":')
            + b"\nSTATUS\n"
        )
        status = rows[-1]["data"]
        self.assertEqual(status["received"], 0)
        self.assertGreaterEqual(status["invalid"], 4)

    def test_stale_late_and_bounded_queue(self):
        rows = self.native(
            self.frame()
            + self.frame()
            + b"TIME 200000\n"
            + self.frame(sequence=2, time=1000)
            + b"STATUS\n"
        )
        status = rows[-1]["data"]
        self.assertEqual(status["stale"], 1)
        self.assertEqual(status["late_updates"], 1)
        raw = b"".join(self.frame(sequence=i + 1, time=i * 1000) for i in range(70))
        status = self.native(raw + b"STATUS\n")[-1]["data"]
        self.assertEqual(status["queue_depth"], 64)
        self.assertEqual(status["queue_overflows"], 6)

    def test_reset_aborts_previous_session(self):
        rows = self.native(
            self.frame()
            + b"TIME 110000\nPIN 0 0 1\n"
            + self.frame(sequence=2, time=0, session=43)
            + b"STATUS\n"
        )
        abort = next(
            e
            for r in rows
            for e in expand_events(r)
            if e["type"] == "ecu_event" and e["data"]["action"] == "aborted"
        )
        self.assertEqual(abort["data"]["hardware_session"], 42)
        self.assertIsNotNone(abort["error"])
        self.assertEqual(rows[-1]["data"]["resets"], 2)

    def test_link_watchdog_and_incomplete_pulse(self):
        rows = self.native(self.frame() + b"TIME 110000\nPIN 1 0 1\nTIME 1100000\nSTATUS\n")
        self.assertTrue(
            any(
                e["type"] == "ecu_event" and e["data"]["action"] == "timeout"
                for r in rows
                for e in expand_events(r)
            )
        )
        self.assertFalse(rows[-1]["data"]["running"])
        self.assertEqual(rows[-1]["data"]["watchdog_timeouts"], 1)

    def test_hardware_restart_and_bad_status_do_not_leave_active_outputs(self):
        engine = Engine()
        bridge = RFC2217Bridge(engine, "unused", hardware=True)
        bridge.hardware_session = 42
        engine.ecu_event(dict(signal="injector", action="start", channel=0, simulation_time_us=0))
        engine.step()
        self.assertTrue(engine.model.open_injectors)
        status = self.native(self.frame() + b"STATUS\n")[-1]
        status["sequence"] = 20
        bridge.receive(decode(encode(status)))
        bad = json.loads(json.dumps(status))
        bad["sequence"] = 21
        bad["data"]["phase_error_deg"] = "bad"
        bridge.receive(decode(encode(bad)))
        self.assertEqual(bridge.metrics["invalid"], 1)
        self.assertEqual(bridge.metrics["hardware"]["phase_error_deg"], 0)
        status["sequence"] = 1
        bridge.receive(decode(encode(status)))
        engine.step()
        self.assertEqual(bridge.metrics["hardware_resets"], 1)
        self.assertFalse(engine.model.open_injectors)
        bridge.close()

    def test_old_session_events_are_rejected(self):
        engine = Engine()
        bridge = RFC2217Bridge(engine, "unused", hardware=True)
        rows = self.native(self.frame() + b"TIME 110000\nPIN 0 0 1\n")
        for row in rows:
            bridge.receive(row)
        engine.step()
        self.assertFalse(engine.model.open_injectors)
        self.assertEqual(bridge.metrics["invalid"], len(rows))
        bridge.close()

    def test_input_aliases(self):
        data = Engine().snapshot()
        data["tps_percent"] = 20
        data["lambda"] = 1.02
        del data["tps"]
        del data["lambda_value"]
        self.assertEqual(self.native(self.frame(**data))[0]["type"], "clock_sync")

    def test_host_inherits_hardware_geometry(self):
        spec = importlib.util.spec_from_file_location("hw_run_host", ROOT / "scripts/run_host.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        hardware = json.loads((ROOT / "config/engine.json").read_text())
        hardware["cylinders"] = 2
        hardware["ckp"]["teeth"] = 36
        hardware["ckp"]["missing"] = 1
        config = module.host_configuration(hardware)
        self.assertEqual(config["engine"]["cylinders"], 2)
        self.assertEqual(config["signals"]["teeth"], 36)
        self.assertEqual(config["signals"]["missing"], 1)
        self.assertIn("inertia", config["engine"])

    def test_configuration_and_pin_conflicts(self):
        engine = ROOT / "config/engine.json"
        pinout = ROOT / "config/pinout.json"
        files = configure.generate(*configure.load(engine, pinout))
        for name, content in files.items():
            self.assertEqual((ROOT / name).read_text(), content)
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "pins.json"
            pins = json.loads(pinout.read_text())
            pins["profiles"]["esp32"]["cmp"] = pins["profiles"]["esp32"]["ckp"]
            path.write_text(json.dumps(pins))
            with self.assertRaises(ValueError):
                configure.load(engine, path)
        fw = (ROOT / "firmware/src/main.cpp").read_text()
        self.assertNotIn("engine_state", fw)
        self.assertNotIn("serial_for_url", fw)


if __name__ == "__main__":
    unittest.main()
