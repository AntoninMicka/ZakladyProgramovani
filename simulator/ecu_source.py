"""Editovatelné vstupy a revize firmware; žádný kód se zde nevykonává."""

import hashlib
import os
from pathlib import Path
import stat
import tempfile
import tomllib

MAX_SOURCE_BYTES = 1024 * 1024


def source_files(project):
    project = Path(project)
    result = []
    for directory in ("firmware/src", "firmware/include", "src"):
        for path in (project / directory).rglob("*"):
            if (
                path.is_file()
                and path.suffix in (".c", ".cpp", ".h", ".hpp")
                and not path.name.startswith("generated_")
            ):
                result.append(path)
    return sorted(result)


def source_revision(project):
    project = Path(project)
    files = source_files(project)
    files += sorted((project / "config").glob("*.json"))
    files += sorted((project / "chips").rglob("*.c"))
    files += sorted((project / "chips").rglob("*.h"))
    files += [project / "platformio.ini"]
    digest = hashlib.sha256()
    for path in sorted(set(files)):
        if path.is_file():
            digest.update(str(path.relative_to(project)).encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


def artifact_revision(project):
    project = Path(project)
    config = tomllib.loads((project / "wokwi.toml").read_text())
    paths = [project / config["wokwi"]["firmware"]]
    paths += [project / chip["binary"] for chip in config.get("chip", [])]
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.read_bytes())
    return digest.hexdigest()


class SourceDocument:
    def __init__(self, path):
        self.path = Path(path)
        if self.path.stat().st_size > MAX_SOURCE_BYTES:
            raise ValueError("Zdrojový soubor je větší než 1 MiB")
        self.saved_bytes = self.path.read_bytes()
        self.text = self.saved_bytes.decode("utf-8")

    def save(self, text):
        if self.path.read_bytes() != self.saved_bytes:
            raise OSError("Soubor se mezitím změnil mimo editor. Nejdříve jej znovu načtěte.")
        raw = text.encode("utf-8")
        if len(raw) > MAX_SOURCE_BYTES:
            raise ValueError("Zdrojový soubor je větší než 1 MiB")
        mode = stat.S_IMODE(self.path.stat().st_mode)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=self.path.parent, prefix=".ecu-", suffix=".tmp", delete=False
            ) as stream:
                temporary = Path(stream.name)
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            temporary.chmod(mode)
            os.replace(temporary, self.path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        self.saved_bytes, self.text = raw, text
