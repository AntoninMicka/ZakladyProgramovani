"""Katalog, skutečné procesy, překlad C a volitelné skutečné Tk widgety."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from launcher.catalog import (
    ROOT,
    PROJECTS,
    Action,
    Plan,
    Project,
    get_project,
    make_plan,
)
from launcher.process import Runner


def wait_for(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("Čekání na výsledek překročilo limit")


class LauncherTests(unittest.TestCase):
    def test_catalog_has_real_documents_sources_and_canonical_ecu_task(self):
        self.assertEqual(len(PROJECTS), 5)
        self.assertEqual(len({p.id for p in PROJECTS}), 5)
        for project in PROJECTS:
            for name in (
                project.overview,
                project.tasks,
                project.readme,
                project.source,
            ):
                self.assertTrue((ROOT / name).is_file(), name)
                self.assertGreater((ROOT / name).stat().st_size, 100)
            self.assertEqual(len({a.id for a in project.actions}), len(project.actions))
        self.assertEqual(
            get_project("ecu").tasks, "simulator/docs/ukol_regulace_otacek.md"
        )
        self.assertIn("requested_rpm", (ROOT / get_project("ecu").tasks).read_text())

    def test_ecu_plan_uses_project_environment_and_does_not_enable_fixed_rpm(self):
        p = get_project("ecu")
        plan = make_plan(p, p.actions[0])
        self.assertIn("--gui", plan.commands[0])
        self.assertNotIn("--rpm", plan.commands[0])
        self.assertEqual(plan.cwd, ROOT / "simulator")
        self.assertEqual(plan.commands[0][0], str(ROOT / "simulator/.venv/bin/python"))

    def test_missing_wokwi_token_fails_before_build(self):
        p = get_project("arduino")
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, "WOKWI_CLI_TOKEN"):
                make_plan(p, p.actions[-1])

    def test_utf8_prompt_and_interactive_input_without_newline(self):
        runner = Runner()
        command = (
            sys.executable,
            "-u",
            "-c",
            "print('Jméno: ',end='',flush=True);print('Ahoj '+input())",
        )
        runner.start(Plan("vstup", ROOT, (command,)))
        seen = []

        def prompt():
            seen.append(runner.drain())
            return "Jméno: " in "".join(seen)

        try:
            wait_for(prompt)
            runner.send("Žofie")
            wait_for(lambda: not runner.busy)
            seen.append(runner.drain())
            self.assertIn("Ahoj Žofie", "".join(seen))
            self.assertEqual(runner.status, "Dokončeno")
        finally:
            runner.stop()
            runner.thread.join(3)

    def test_failed_step_does_not_run_previous_binary(self):
        runner = Runner()
        runner.start(
            Plan(
                "chyba",
                ROOT,
                (
                    (sys.executable, "-c", "raise SystemExit(7)"),
                    (sys.executable, "-c", "print('STALE_BINARY')"),
                ),
            )
        )
        wait_for(lambda: not runner.busy)
        self.assertEqual(runner.exit_code, 7)
        self.assertNotIn("STALE_BINARY", runner.drain())

    def test_stop_and_reject_concurrent_start(self):
        runner = Runner()
        plan = Plan(
            "čekání",
            ROOT,
            (
                (
                    sys.executable,
                    "-u",
                    "-c",
                    "import time;print('ready');time.sleep(60)",
                ),
            ),
        )
        runner.start(plan)
        wait_for(lambda: runner.process is not None)
        with self.assertRaises(ValueError):
            runner.start(plan)
        runner.stop()
        wait_for(lambda: not runner.busy)
        if runner.stop_thread:
            runner.stop_thread.join(3)
        self.assertEqual(runner.status, "Zastaveno")
        self.assertIsNone(runner.process)

    def test_output_queue_is_bounded(self):
        runner = Runner()
        for _ in range(1000):
            runner.emit("výstup")
        self.assertEqual(runner.messages.qsize(), 512)
        self.assertEqual(runner.dropped, 488)

    def test_wokwi_timeout_success_only_for_final_wokwi_step(self):
        runner = Runner()
        runner.start(
            Plan("Wokwi", ROOT, ((sys.executable, "-c", "raise SystemExit(42)"),), True)
        )
        wait_for(lambda: not runner.busy)
        self.assertEqual(runner.status, "Dokončeno · časový limit Wokwi")

    def test_real_c_compile_run_and_cwd_with_spaces(self):
        with tempfile.TemporaryDirectory(prefix="launcher tests ") as directory:
            root = Path(directory)
            project_dir = root / "projekt s mezerou"
            project_dir.mkdir()
            (project_dir / "input.txt").write_text("42")
            (project_dir / "main.c").write_text(
                '#include <stdio.h>\nint main(void){int n;FILE *f=fopen("input.txt","r");if(!f)return 1;if(fscanf(f,"%d",&n)!=1)return 2;fclose(f);printf("RESULT=%d\\n",n);return 0;}'
            )
            project = Project(
                "c", "Test C", "", "projekt s mezerou", "", "", "", "", ()
            )
            with patch("launcher.catalog.ROOT", root):
                plan = make_plan(project, Action("run", "C", "c", "main.c"))
            runner = Runner()
            runner.start(plan)
            wait_for(lambda: not runner.busy)
            self.assertEqual(runner.exit_code, 0, runner.status)
            self.assertIn("RESULT=42", runner.drain())

    def test_cli_list_and_tasks_from_another_working_directory(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "spustit.py"), "--tasks", "ecu"],
            cwd="/tmp",
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertIn("update_control", result.stdout)
        self.assertIn("regulátor", result.stdout)
        result = subprocess.run(
            [sys.executable, str(ROOT / "spustit.py"), "--list"],
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertIn("quadrokoptera", result.stdout)


@unittest.skipUnless(
    os.environ.get("LAUNCHER_TEST_GUI") == "1",
    "enable with LAUNCHER_TEST_GUI=1 and a display",
)
class LauncherGuiTests(unittest.TestCase):
    def make_view(self):
        import tkinter as tk
        from launcher.gui import Launcher

        root = tk.Tk()
        view = Launcher(root)
        root.update()
        return root, view

    def test_projects_tasks_and_exact_source_display(self):
        root, view = self.make_view()
        try:
            root.geometry("960x700")
            root.update()
            self.assertLessEqual(
                view.input.winfo_rooty() + view.input.winfo_height(),
                root.winfo_rooty() + root.winfo_height(),
            )
            self.assertEqual(view.project.id, "ecu")
            self.assertIn("requested_rpm", view.tasks.text.get("1.0", "end"))
            view.select_project("python")
            view.show_source()
            self.assertIn("# 1. KOMENTÁŘE", view.documentation.text.get("1.0", "end"))
            view.search.set("Arduino")
            self.assertEqual(len(view.visible), 1)
            self.assertEqual(view.project.id, "arduino")
        finally:
            view.close()

    def test_actual_python_launch_output_and_navigation_while_running(self):
        root, view = self.make_view()
        try:
            view.select_project("python")
            view.start()
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                root.update()
                if not view.runner.busy and "Proměnné a typy" in view.output.get(
                    "1.0", "end"
                ):
                    break
                time.sleep(0.01)
            self.assertFalse(view.runner.busy)
            self.assertIn("Proměnné a typy", view.output.get("1.0", "end"))
            self.assertEqual(view.runner.exit_code, 0)
            view.select_project("ecu")
            self.assertIn("regulátor", view.tasks.text.get("1.0", "end"))
        finally:
            view.close()

    def test_close_stops_owned_child_without_blocking_window(self):
        root, view = self.make_view()
        plan = Plan(
            "čekání",
            ROOT,
            (
                (
                    sys.executable,
                    "-u",
                    "-c",
                    "import time;print('ready');time.sleep(60)",
                ),
            ),
        )
        view.runner.start(plan)
        wait_for(lambda: view.runner.process is not None)
        view.close()
        deadline = time.monotonic() + 5
        while not view.closed and time.monotonic() < deadline:
            root.update()
            time.sleep(0.01)
        self.assertTrue(view.closed)
        self.assertFalse(view.runner.busy)
