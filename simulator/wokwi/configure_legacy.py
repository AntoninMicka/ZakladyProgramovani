#!/usr/bin/env python3
"""Legacy chip přebírá geometrii ze stejného JSON jako Python."""

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))
from signals import SignalGenerator


def generate(settings):
    generator = SignalGenerator(**settings["signals"])
    if len(generator.cmp_positions) > 8:
        raise ValueError("legacy supports at most 8 CMP pulses")
    return (
        "// Generated from ../engine_config.json; run configure_legacy.py.\n"
        f"#define LEGACY_TEETH {generator.teeth}\n"
        f"#define LEGACY_PRESENT {generator.teeth - generator.missing}\n"
        f"#define LEGACY_CMP_COUNT {len(generator.cmp_positions)}\n"
        f"#define LEGACY_CMP_WIDTH {generator.cmp_width}\n"
        "static const double LEGACY_CMP_POSITIONS[] = {"
        + ",".join(str(value) for value in generator.cmp_positions)
        + "};\n"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    content = generate(json.loads((ROOT.parent / "engine_config.json").read_text()))
    path = ROOT / "generated_legacy.h"
    if args.check:
        if not path.exists() or path.read_text() != content:
            parser.exit(1, "Stale generated_legacy.h\n")
    else:
        path.write_text(content)
