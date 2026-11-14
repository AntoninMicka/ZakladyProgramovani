import json
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch
from engine import Engine
from model import EngineModel
from supervisor import Supervisor
from transport import ConnectionWorker
from ecu_source import SourceDocument, source_revision
from telemetry import serialize_record


class ReviewFixTests(unittest.TestCase):
    def test_invalidation_preserves_last_valid_dose_and_discards_future(self):
        e = Engine()
        e.command({"injector_ms": 3.75})
        e.step()
        e.ecu_event(dict(signal="injector", action="start", channel=0, simulation_time_us=100000))
        e.step()
        self.assertTrue(e.pending)
        e.invalidate()
        e.step()
        self.assertEqual(e.model.injector_ms, 3.75)
        self.assertFalse(e.pending)

    def test_far_future_events_do_not_fill_queue(self):
        e = Engine()
        e.ecu_event(
            dict(
                signal="injector",
                action="start",
                channel=0,
                simulation_time_us=999999999,
            )
        )
        e.step()
        self.assertFalse(e.pending)
        self.assertEqual(e.diagnostics["future_events_rejected"], 1)

    def test_pacing_resets_only_wall_debt(self):
        e = Engine()
        e.step()
        before = e.clock.time_us
        self.assertEqual(e.bound_deadline(1, 61), 61)
        self.assertEqual(e.clock.time_us, before)
        self.assertEqual(e.diagnostics["pacing_resets"], 1)
        self.assertEqual(e.bound_deadline(10, 10.1), 10)

    def test_default_model_runs_and_fixed_rpm_can_be_disabled(self):
        m = EngineModel()
        for _ in range(10000):
            m.step(0.001)
        self.assertGreater(m.rpm, 0)
        m.command({"rpm": 1200})
        m.step(0.1)
        self.assertEqual(m.rpm, 1200)
        m.command({"rpm": None, "load_nm": 100})
        m.step(0.1)
        self.assertLess(m.rpm, 1200)

    def test_restart_restores_cli_initial_values(self):
        app = Supervisor()
        app.configure_initial({"throttle": 0.6, "load_nm": 25, "rpm": 1500})
        app.engine.command({"throttle": 0.2, "load_nm": 50, "rpm": None})
        app.engine.step()
        app.restart()
        app.engine.step()
        self.assertEqual(app.engine.model.throttle, 0.6)
        self.assertEqual(app.engine.model.load_nm, 25)
        self.assertEqual(app.engine.model.target_rpm, 1500)
        app.close()

    def test_unrequested_edges_are_not_computed(self):
        e = Engine()
        with patch.object(e.signals, "edges", side_effect=AssertionError("unused work")):
            e.step()
        self.assertTrue(e.events.empty())

    def test_transport_drains_outgoing_burst_before_read(self):
        seen = []
        read = threading.Event()

        class Transport:
            def open(self):
                pass

            def write(self, raw):
                seen.append(raw)

            def read(self):
                read.set()
                return b""

            def close(self):
                pass

        worker = ConnectionWorker(Transport, lambda raw: None)
        worker.connected.set()

        # Run directly, without connection startup clearing the prefilled queue.
        def on_connect():
            for i in range(4):
                worker.outgoing.put_nowait(bytes([i]))

        worker.on_connect = on_connect
        worker.start()
        self.assertTrue(read.wait(1))
        worker.close()
        self.assertEqual(seen, [bytes([i]) for i in range(4)])

    def test_serialization_rejects_nonfinite_values(self):
        with self.assertRaises(ValueError):
            serialize_record({"rpm": float("nan")}, {}, 0)

    def test_source_save_conflict_and_revision(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            source = project / "firmware/src/main.cpp"
            source.parent.mkdir(parents=True)
            source.write_text("void loop() {}\n")
            document = SourceDocument(source)
            before = source_revision(project)
            document.save("void loop() { /* změna */ }\n")
            self.assertNotEqual(before, source_revision(project))
            source.write_text("external change")
            with self.assertRaises(OSError):
                document.save("must not overwrite")
            self.assertEqual(source.read_text(), "external change")

    def test_legacy_integer_clock_precision_and_reanchor(self):
        root = Path(__file__).resolve().parents[1]
        source = r"""
#include <assert.h>
#include "legacy_time.h"
int main() {
 uint32_t value;
 assert(read_u32("{\"simulation_time_us\":16777217}","simulation_time_us",value));
 assert(value==16777217u);
 assert(read_u32("{\"time\":4000000001}","time",value));assert(value==4000000001u);
 assert(!read_u32("{\"time\":4294967296}","time",value));
 assert(!read_u32("{\"time\":1.5}","time",value));
 LegacyTime c;c.update(16777217,1000,1,.02);assert(c.map(900000,1000)==16777217u);
 c.update(16777237,2000,1,.02);assert(c.map(901000,2000)==16777237u);
 c.update(10,3000,2,.02);assert(c.map(902000,3000)==10u);
 LegacyPulse pulse;pulse.start(100000,10,.02);uint32_t mapped,duration;
 assert(pulse.end(103000,mapped,duration));assert(mapped==70 && duration==3000);
}"""
        with tempfile.TemporaryDirectory() as directory:
            cpp = Path(directory) / "clock.cpp"
            cpp.write_text(source)
            binary = Path(directory) / "clock"
            subprocess.run(
                [
                    "clang++-21",
                    "-std=c++17",
                    "-Wall",
                    "-Wextra",
                    "-Werror",
                    "-I",
                    str(root / "wokwi/src"),
                    str(cpp),
                    "-o",
                    str(binary),
                ],
                check=True,
            )
            subprocess.run([binary], check=True)
