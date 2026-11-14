#!/usr/bin/env python3
"""Konfigurace + build skutečného firmware a WASM, bez tvrzení o Wokwi runtime."""

import argparse
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", choices=["esp32", "mega"], default="esp32")
    parser.add_argument("--pio", default=shutil.which("pio") or shutil.which("platformio"))
    parser.add_argument("--wokwi-cli", default=shutil.which("wokwi-cli"))
    args = parser.parse_args()
    if not args.pio or not args.wokwi_cli:
        parser.error("Install PlatformIO and wokwi-cli or provide --pio and --wokwi-cli")
    subprocess.run(
        [sys.executable, str(ROOT / "scripts/configure.py"), "--target", args.target],
        check=True,
    )
    subprocess.run([args.pio, "run", "-d", str(ROOT), "-e", args.target], check=True)
    subprocess.run(
        [
            args.wokwi_cli,
            "chip",
            "compile",
            "engine-interface.chip.c",
            "hw_core.c",
            "adapter.c",
            "json.c",
            "-o",
            "engine-interface.chip.wasm",
        ],
        cwd=ROOT / "chips/engine-interface",
        check=True,
    )
    for name in ("sensor-front-end", "output-stage"):
        subprocess.run(
            [args.wokwi_cli, "chip", "compile", name + ".chip.c", "-o", name + ".chip.wasm"],
            cwd=ROOT / "chips" / name,
            check=True,
        )
    subprocess.run([args.wokwi_cli, "lint", str(ROOT)], check=True)
    for path in (
        ROOT / f".pio/build/{args.target}/firmware.elf",
        ROOT / f".pio/build/{args.target}/firmware.{'bin' if args.target == 'esp32' else 'hex'}",
        ROOT / "chips/engine-interface/engine-interface.chip.wasm",
        ROOT / "chips/sensor-front-end/sensor-front-end.chip.wasm",
        ROOT / "chips/output-stage/output-stage.chip.wasm",
    ):
        if not path.is_file() or not path.stat().st_size:
            raise RuntimeError("Missing artifact " + str(path))
    print("Build artifacts verified; Wokwi integration still requires a runtime test.")


if __name__ == "__main__":
    main()
