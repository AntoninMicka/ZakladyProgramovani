"""Katalog projektů, jejich skutečných akcí, dokumentace a studentských úkolů."""

from dataclasses import dataclass
from pathlib import Path
import os
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Action:
    id: str
    title: str
    kind: str
    source: str = ""
    note: str = ""


@dataclass(frozen=True)
class Project:
    id: str
    title: str
    subtitle: str
    directory: str
    overview: str
    tasks: str
    readme: str
    source: str
    actions: tuple[Action, ...]


PROJECTS = (
    Project(
        "python",
        "1 · Python a konzole",
        "Proměnné, podmínky, cykly, soubory a Git",
        "prvni_hodina",
        "launcher/materialy/python.md",
        "launcher/materialy/python_ukoly.md",
        "prvni_hodina/README.md",
        "prvni_hodina/zaklady_pythonu.py",
        (
            Action(
                "zaklady", "Spustit základy Pythonu", "python", "zaklady_pythonu.py"
            ),
            Action(
                "soubory",
                "Spustit rozdělení čísel",
                "python",
                "ukol_soubory.py",
                "Přepíše sude.txt a liche.txt vedle programu.",
            ),
            Action(
                "bash",
                "Spustit průvodce Bash / Git",
                "bash",
                "zaklady_konzole.sh",
                "Odpovědi zadávejte dole do výstupu. Vytvoří cvičnou složku v /tmp; klonování je volitelné.",
            ),
            Action(
                "powershell",
                "Spustit průvodce PowerShell",
                "powershell",
                "zaklady_powershellu.ps1",
                "Vyžaduje PowerShell. Volitelné kroky skriptu potvrzuje student sám.",
            ),
        ),
    ),
    Project(
        "c",
        "2 · Základy jazyka C",
        "Překlad C17 a práce s textovými soubory",
        "druha_hodina_zaklady_C",
        "launcher/materialy/c.md",
        "launcher/materialy/c_ukoly.md",
        "druha_hodina_zaklady_C/README.md",
        "druha_hodina_zaklady_C/zaklady_c.c",
        (
            Action("zaklady", "Přeložit a spustit základy C", "c", "zaklady_c.c"),
            Action(
                "soubory",
                "Přeložit a spustit rozdělení čísel",
                "c",
                "ukol_soubory.c",
                "Přepíše sude.txt a liche.txt v projektu. Překlad proběhne před každým spuštěním.",
            ),
        ),
    ),
    Project(
        "arduino",
        "3 · Arduino: sériová linka",
        "LED, A/D převod a krokový motor s ručičkou",
        "druha_hodina",
        "launcher/materialy/arduino.md",
        "launcher/materialy/arduino_ukoly.md",
        "druha_hodina/README.md",
        "druha_hodina/src/main.cpp",
        (
            Action(
                "editor",
                "Otevřít projekt ve VSCodiu / VS Code",
                "editor",
                note="V editoru sestavte firmware a zvolte Wokwi: Start Simulator. Otevření složky samo simulaci nespouští.",
            ),
            Action("build", "Sestavit Arduino firmware", "platformio"),
            Action(
                "wokwi",
                "Sestavit a spustit Wokwi CLI na 6 s",
                "wokwi",
                note="Vyžaduje WOKWI_CLI_TOKEN v prostředí; může čerpat CI kvótu. Jde o konzolový běh, schéma otevřete v editoru.",
            ),
        ),
    ),
    Project(
        "quadrokoptera",
        "4 · Řadič kvadrokoptéry",
        "IMU, náklon, ARM a směšování čtyř výstupů",
        "quadroptera_wokwi",
        "launcher/materialy/quadrokoptera.md",
        "launcher/materialy/quadrokoptera_ukoly.md",
        "quadroptera_wokwi/README.md",
        "quadroptera_wokwi/src/main.cpp",
        (
            Action(
                "editor",
                "Otevřít projekt ve VSCodiu / VS Code",
                "editor",
                note="V editoru sestavte firmware a zvolte Wokwi: Start Simulator. Otevření složky samo simulaci nespouští.",
            ),
            Action("build", "Sestavit firmware řadiče", "platformio"),
            Action(
                "wokwi",
                "Sestavit a spustit Wokwi CLI na 6 s",
                "wokwi",
                note="Vyžaduje WOKWI_CLI_TOKEN; může čerpat CI kvótu. Vstupní periferie ovládejte při vizuálním běhu v editoru.",
            ),
        ),
    ),
    Project(
        "ecu",
        "5 · ECU simulátor motoru",
        "Motor, společný C++ řadič a editor ECU",
        "simulator",
        "launcher/materialy/ecu.md",
        "simulator/docs/ukol_regulace_otacek.md",
        "simulator/README.md",
        "simulator/wokwi/hardware/firmware/include/ecu_controller.h",
        (
            Action(
                "gui",
                "Spustit ECU simulátor s GUI",
                "ecu_gui",
                note="Mock používá společnou C++ ECU. Pro studentskou regulaci nepoužívejte stolici --rpm.",
            ),
            Action("konzole", "Spustit ECU Mock na 10 s v konzoli", "ecu_cli"),
            Action("editor", "Otevřít ECU projekt ve VSCodiu / VS Code", "editor"),
        ),
    ),
)


def get_project(identifier):
    for project in PROJECTS:
        if project.id == identifier:
            return project
    raise ValueError("Neznámý projekt: " + identifier)


def find_tool(names, candidates=()):
    for name in names:
        if found := shutil.which(name):
            return found
    for path in candidates:
        if Path(path).is_file() and os.access(path, os.X_OK):
            return str(path)
    raise ValueError(
        "Chybí nástroj: "
        + " / ".join(names)
        + ". Postup instalace je v popisu projektu."
    )


def python_for(project):
    if project.id == "ecu":
        # Nevolat resolve(): přesměrování symlinku python mimo .venv by ztratilo prostředí.
        path = ROOT / project.directory / ".venv/bin/python"
        if path.is_file():
            return str(path)
    return sys.executable


@dataclass(frozen=True)
class Plan:
    title: str
    cwd: Path
    commands: tuple[tuple[str, ...], ...]
    timeout_is_success: bool = False


def make_plan(project, action):
    directory = ROOT / project.directory
    if not directory.is_dir():
        raise ValueError("Chybí adresář projektu: " + str(directory))
    kind = action.kind
    if kind == "python":
        commands = [(python_for(project), "-u", str(directory / action.source))]
    elif kind in ("ecu_gui", "ecu_cli"):
        command = [
            python_for(project),
            "-u",
            str(directory / "main.py"),
            "--mode",
            "mock",
        ]
        command += ["--gui"] if kind == "ecu_gui" else ["--duration", "10"]
        commands = [tuple(command)]
    elif kind == "c":
        compiler = find_tool(("gcc", "clang"))
        output = ROOT / ".cache/launcher" / project.id / Path(action.source).stem
        output.parent.mkdir(parents=True, exist_ok=True)
        commands = [
            (
                compiler,
                "-std=c17",
                "-Wall",
                "-Wextra",
                "-Wpedantic",
                str(directory / action.source),
                "-o",
                str(output),
            ),
            (str(output),),
        ]
    elif kind == "bash":
        commands = [(find_tool(("bash",)), str(directory / action.source))]
    elif kind == "powershell":
        commands = [
            (
                find_tool(("pwsh", "powershell")),
                "-NoProfile",
                "-File",
                str(directory / action.source),
            )
        ]
    elif kind == "editor":
        commands = [(find_tool(("codium", "code")), "--new-window", str(directory))]
    elif kind in ("platformio", "wokwi"):
        if kind == "wokwi" and not os.environ.get("WOKWI_CLI_TOKEN"):
            raise ValueError(
                "Pro Wokwi CLI chybí WOKWI_CLI_TOKEN. Nastavte jej před spuštěním rozcestníku, nebo použijte vizuální Wokwi v editoru."
            )
        pio = find_tool(
            ("pio", "platformio"), (Path.home() / ".platformio/penv/bin/pio",)
        )
        commands = [(pio, "run", "-d", str(directory), "-e", "uno")]
        if kind == "wokwi":
            cli = find_tool(("wokwi-cli",), (ROOT / "simulator/.venv/bin/wokwi-cli",))
            commands.append((cli, str(directory), "--timeout", "6000"))
    else:
        raise ValueError("Nepodporovaná akce: " + kind)
    return Plan(
        project.title + " · " + action.title,
        directory,
        tuple(commands),
        kind == "wokwi",
    )
