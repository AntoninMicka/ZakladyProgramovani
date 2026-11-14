"""Regenerace geometrie před každým překladem legacy firmware."""

import runpy
from pathlib import Path

Import("env")
root = Path(env.subst("$PROJECT_DIR"))
namespace = runpy.run_path(str(root / "configure_legacy.py"))
settings = namespace["json"].loads((root.parent / "engine_config.json").read_text())
(root / "generated_legacy.h").write_text(namespace["generate"](settings))
