#!/usr/bin/env python3
"""Centrální spouštěč výukových projektů: GUI nebo terminálové rozhraní."""

import argparse
import os
import subprocess
import sys
from launcher.catalog import ROOT, PROJECTS, get_project, make_plan


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--list", action="store_true", help="Vypsat projekty a akce")
    mode.add_argument("--describe", metavar="ID", help="Podrobný popis projektu")
    mode.add_argument("--tasks", metavar="ID", help="Studentské zadání")
    mode.add_argument("--run", metavar="ID", help="Spustit projekt bez rozcestníku GUI")
    parser.add_argument("--action", metavar="AKCE", help="ID akce z --list")
    args = parser.parse_args()
    if args.action and not args.run:
        parser.error("--action vyžaduje --run ID")
    try:
        if args.list:
            for p in PROJECTS:
                print(
                    f"{p.id}: {p.title}\n  "
                    + " | ".join(a.id + " = " + a.title for a in p.actions)
                )
        elif args.describe or args.tasks:
            project = get_project(args.describe or args.tasks)
            print(
                (
                    ROOT / (project.overview if args.describe else project.tasks)
                ).read_text()
            )
        elif args.run:
            project = get_project(args.run)
            action = (
                next((a for a in project.actions if a.id == args.action), None)
                if args.action
                else project.actions[0]
            )
            if action is None:
                raise ValueError("Neznámá akce. Použijte --list pro seznam.")
            plan = make_plan(project, action)
            print(plan.title, flush=True)
            environment = dict(
                os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8"
            )
            for command in plan.commands:
                code = subprocess.run(command, cwd=plan.cwd, env=environment).returncode
                if code and not (
                    plan.timeout_is_success
                    and code == 42
                    and command == plan.commands[-1]
                ):
                    return code
        else:
            try:
                from launcher.gui import run_gui

                run_gui()
            except ImportError:
                raise ValueError(
                    "GUI vyžaduje python3-tk. Do té doby použijte --list, --describe, --tasks nebo --run."
                )
            except Exception as exc:
                if type(exc).__name__ == "TclError":
                    raise ValueError(
                        "Nelze otevřít displej. Spusťte aplikaci v grafickém prostředí; v terminálu je dostupné --list a --run."
                    ) from exc
                raise
        return 0
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
