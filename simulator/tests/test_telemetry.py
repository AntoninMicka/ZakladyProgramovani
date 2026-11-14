import json
import unittest
from engine import Engine
from telemetry import TelemetryBuffer, format_sample


class TelemetryTests(unittest.TestCase):
    def test_readable_values_and_link(self):
        state = Engine().snapshot()
        text = format_sample(state, {"connected": False}, 1.25)
        for part in (
            "wall=",
            "sim=",
            "RPM=",
            "TPS=",
            "MAP=",
            "inj=",
            "spark=",
            "CKP/CMP=",
            "link=offline",
            "lost=0",
            "late=0",
            "rejected=0",
        ):
            self.assertIn(part, text)
        self.assertIn("link=mock", format_sample(state, {}, 0))

    def test_bounded_independent_samples(self):
        state = Engine().snapshot()
        archive = TelemetryBuffer(2)
        for i in range(4):
            archive.append(state, {"received": i}, i)
        state["diagnostics"]["late_events"] = 999
        records = [json.loads(line) for line in archive.jsonl().splitlines()]
        self.assertEqual(len(records), 2)
        self.assertEqual([r["wall_elapsed_s"] for r in records], [2, 3])
        self.assertEqual(records[-1]["state"]["diagnostics"]["late_events"], 0)
        self.assertEqual(archive.total, 4)
        self.assertEqual(len(archive.text().splitlines()), 2)
        archive.clear()
        self.assertEqual(archive.jsonl(), "")
        self.assertEqual(archive.total, 0)

    def test_invalid_capacity(self):
        with self.assertRaises(ValueError):
            TelemetryBuffer(0)
