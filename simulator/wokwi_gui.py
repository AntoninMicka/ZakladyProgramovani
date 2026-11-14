"""Tk ovládání Wokwi CLI. Spouští se pouze na výslovné stisknutí tlačítka."""

from dataclasses import replace
from collections import deque
import json
import os
from pathlib import Path
import queue
import sys
import tempfile
from threading import Event, Thread
import tkinter as tk
from tkinter import ttk, filedialog
import tomllib
import webbrowser
from time import monotonic
from signals import SignalGenerator
from ecu_source import source_revision, artifact_revision
from wokwi_process import WokwiProcess, ProcessTransport, find_cli, find_pio

ROOT = Path(__file__).resolve().parent


class WokwiPanel:
    def __init__(self, page, app, runner=None):
        self.app = app
        self.runner = runner or WokwiProcess()
        self.builder = WokwiProcess()
        self.build_context = None
        self.pending_apply = None
        self.built_revision = None
        self.built_artifacts = None
        self.running_revision = None
        self.launch_revision = None
        self.build_status = "Zatím nesestaveno v tomto okně."
        self.build_lines = deque(maxlen=30)
        self._session_token = ""
        self.operation = None
        self.cancel_operation = Event()
        self.results = queue.Queue(4)
        self.closed = False
        self.job = None
        self.await_hardware = False
        self.hardware_confirmed = False
        self.wait_since = 0
        self.log_rows = 0
        self.operation_error = ""
        self.project = tk.StringVar(value=str(ROOT / "wokwi/hardware"))
        self.cli = tk.StringVar(value=find_cli())
        self.token = tk.StringVar()
        self.mode = tk.StringVar(value="Prototyp (scénář)")
        self.timeout = tk.StringVar(value="6000")
        self.scenario = tk.StringVar(value="tests/prototype.yaml")
        self.output_path = tk.StringVar(value="VCD se vytvoří při novém spuštění")
        self.status = tk.StringVar(value="Připraveno · žádná simulace neběží")
        self._build(page)

    @property
    def busy(self):
        return self.operation is not None and self.operation.is_alive()

    def _build(self, page):
        form = ttk.Frame(page)
        form.pack(fill="x")
        form.columnconfigure(1, weight=1)
        for row, (label, var, picker) in enumerate(
            [
                ("Wokwi CLI", self.cli, self.pick_cli),
                ("Projekt", self.project, self.pick_project),
            ]
        ):
            ttk.Label(form, text=label).grid(row=row, column=0, sticky="w", padx=(0, 10), pady=4)
            ttk.Entry(form, textvariable=var).grid(row=row, column=1, sticky="ew", pady=4)
            ttk.Button(form, text="Vybrat…", command=picker).grid(row=row, column=2, padx=(8, 0))
        ttk.Label(form, text="Token pro toto spuštění").grid(row=2, column=0, sticky="w", pady=4)
        ttk.Entry(form, textvariable=self.token, show="•").grid(
            row=2, column=1, sticky="ew", pady=4
        )
        ttk.Button(
            form,
            text="Získat token…",
            command=lambda: webbrowser.open("https://wokwi.com/dashboard/ci"),
        ).grid(row=2, column=2, padx=(8, 0))
        token_state = (
            "WOKWI_CLI_TOKEN je v prostředí · pole lze ponechat prázdné."
            if os.environ.get("WOKWI_CLI_TOKEN")
            else "Token v prostředí není · zadejte jej do skrytého pole nebo spusťte GUI z terminálu s exportovaným tokenem."
        )
        ttk.Label(
            page,
            text=token_state
            + " Token se neukládá na disk; pro vyžádané restarty zůstává jen v paměti okna.",
            wraplength=1080,
        ).pack(anchor="w", pady=(4, 10))
        options = ttk.Frame(page)
        options.pack(fill="x")
        ttk.Label(options, text="Běh").pack(side="left")
        ttk.Combobox(
            options,
            textvariable=self.mode,
            state="readonly",
            width=24,
            values=("Prototyp (scénář)", "Živá smyčka motoru"),
        ).pack(side="left", padx=8)
        ttk.Label(options, text="Limit simulace [ms]").pack(side="left", padx=(10, 4))
        ttk.Entry(options, textvariable=self.timeout, width=10).pack(side="left")
        ttk.Label(options, text="Scénář").pack(side="left", padx=(14, 4))
        ttk.Entry(options, textvariable=self.scenario, width=27).pack(
            side="left", fill="x", expand=True
        )
        ttk.Label(
            page,
            text="Prototyp používá pevné vstupní stavy. Živá smyčka propojí model s CLI a čeká na potvrzení hardware.",
        ).pack(anchor="w", pady=(8, 2))
        ttk.Label(
            page,
            text="Živá smyčka začíná při 1×. Pauza motoru nepozastaví Wokwi; tlačítko Zastavit ukončí CLI.",
        ).pack(anchor="w", pady=(0, 2))
        ttk.Label(
            page,
            text="Spuštění může čerpat Wokwi CI kvótu. Po skončení nebo chybě se samo neopakuje.",
        ).pack(anchor="w", pady=(0, 10))
        actions = ttk.Frame(page)
        actions.pack(fill="x")
        self.start_button = ttk.Button(actions, text="Spustit Wokwi", command=self.start)
        self.start_button.pack(side="left")
        self.stop_button = ttk.Button(actions, text="Zastavit", command=self.stop, state="disabled")
        self.stop_button.pack(side="left", padx=8)
        self.build_button = ttk.Button(actions, text="Sestavit firmware a chip", command=self.build)
        self.build_button.pack(side="left")
        self.check_button = ttk.Button(actions, text="Ověřit CLI", command=self.check_cli)
        self.check_button.pack(side="left", padx=8)
        ttk.Button(actions, text="Vymazat výpis", command=self.clear_log).pack(side="right")
        ttk.Label(page, textvariable=self.status, wraplength=1050).pack(anchor="w", pady=10)
        ttk.Entry(page, textvariable=self.output_path, state="readonly").pack(fill="x", pady=(0, 8))
        log_frame = ttk.Frame(page)
        log_frame.pack(fill="both", expand=True)
        self.log = tk.Text(
            log_frame,
            bg="#1e293b",
            fg="#e2e8f0",
            font=("Monospace", 10),
            wrap="none",
            state="disabled",
            height=14,
        )
        vertical = ttk.Scrollbar(log_frame, orient="vertical", command=self.log.yview)
        horizontal = ttk.Scrollbar(log_frame, orient="horizontal", command=self.log.xview)
        self.log.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.log.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        log_frame.rowconfigure(0, weight=1)
        log_frame.columnconfigure(0, weight=1)

    def pick_cli(self):
        selected = filedialog.askopenfilename(title="Wokwi CLI")
        if selected:
            self.cli.set(selected)

    def pick_project(self):
        selected = filedialog.askdirectory(title="Projekt s wokwi.toml")
        if selected:
            self.project.set(selected)

    def _paths(self, artifacts=False):
        cli = Path(self.cli.get()).expanduser().resolve()
        project = Path(self.project.get()).expanduser().resolve()
        if not cli.is_file() or not os.access(cli, os.X_OK):
            raise ValueError("Vyberte spustitelný soubor wokwi-cli (např. .venv/bin/wokwi-cli).")
        config = tomllib.loads((project / "wokwi.toml").read_text())
        if not (project / "diagram.json").is_file():
            raise ValueError("V projektu chybí diagram.json")
        if artifacts:
            paths = [project / config["wokwi"]["firmware"]]
            paths += [project / c["binary"] for c in config.get("chip", [])]
            if any(not p.is_file() or not p.stat().st_size for p in paths):
                raise ValueError(
                    "Chybí firmware nebo WASM. Nejprve použijte Sestavit firmware a chip."
                )
        return cli, project

    def _task(self, function):
        if self.busy or self.runner.busy:
            raise RuntimeError("Nejprve zastavte probíhající operaci.")
        self.cancel_operation = Event()
        self.operation_error = ""
        cancel = self.cancel_operation

        def post(result):
            try:
                self.results.put_nowait(result)
            except queue.Full:
                self.results.get_nowait()
                self.results.put_nowait(result)

        def run():
            try:
                if not cancel.is_set():
                    function()
                if cancel.is_set():
                    self.runner.stop()
                post(("ok", ""))
            except Exception as exc:
                # Token nikdy nevkládáme do příkazu ani do textu výjimky.
                post(("error", str(exc)))

        self.operation = Thread(target=run, name="wokwi-gui-operation", daemon=False)
        self.operation.start()

    def start(self):
        try:
            cli, project = self._paths(artifacts=True)
            timeout = int(self.timeout.get())
            if not 1 <= timeout <= 3600000:
                raise ValueError("Limit musí být 1–3600000 ms virtuálního času.")
            token = self.token.get().strip() or self._session_token
            if not token and not os.environ.get("WOKWI_CLI_TOKEN"):
                raise ValueError(
                    "Nastavte WOKWI_CLI_TOKEN v terminálu nebo zadejte token do skrytého pole."
                )
            live = self.mode.get() == "Živá smyčka motoru"
            command = [str(cli), ".", "--timeout", str(timeout)]
            config = signal_config = hardware = None
            if live:
                hardware = json.loads((project / "config/engine.json").read_text())
                config = replace(self.app.engine.config, cylinders=hardware["cylinders"])
                signal_config = SignalGenerator(
                    teeth=hardware["ckp"]["teeth"],
                    missing=hardware["ckp"]["missing"],
                    cmp_positions=hardware["cmp"]["positions_deg"],
                    cmp_width=hardware["cmp"]["width_deg"],
                )
                command += ["--interactive", "--quiet"]
            else:
                scenario = (project / self.scenario.get()).resolve()
                if not scenario.is_file():
                    raise ValueError("Vyberte existující testovací scénář.")
                command += ["--scenario", str(scenario)]
            output_root = project / "runs"
            output_root.mkdir(exist_ok=True)
            output = Path(tempfile.mkdtemp(prefix="wokwi-", dir=output_root)) / "capture.vcd"
            command += ["--vcd-file", str(output)]
            self.output_path.set(str(output))

            def launch():
                if live:
                    self.app.pause()
                    self.runner.start(command, project, token=token, capture_frames=True)
                    comm = hardware["communication"]
                    self.app.switch_backend(
                        "wokwi",
                        "cli://managed",
                        comm["baudrate"],
                        hardware=True,
                        hardware_mode=comm["mode"],
                        lookahead_us=comm["lookahead_us"],
                        config=config,
                        signals=signal_config,
                        reset=True,
                        paused=True,
                        transport_factory=lambda: ProcessTransport(self.runner),
                    )
                    self.app.engine.set_speed(1)
                else:
                    if self.app.mode != "mock":
                        self.app.switch_backend("mock", paused=True)
                    self.runner.start(command, project, token=token)

            self._task(launch)
            self._session_token = token
            self.token.set("")
            self.launch_revision = None
            if self.built_revision == source_revision(
                project
            ) and self.built_artifacts == artifact_revision(project):
                self.launch_revision = self.built_revision
            self.job = "live" if live else "scenario"
            self.await_hardware = live
            self.hardware_confirmed = False
            self.wait_since = monotonic()
            self.status.set("Spouštím Wokwi…")
            return True
        except (OSError, ValueError, RuntimeError, KeyError, TypeError) as exc:
            self.status.set(str(exc))
            return False

    def build(self, apply_after=False):
        """Build běží odděleně: neúspěch nesmí odstavit starý firmware."""
        try:
            if (
                self.builder.busy
                or self.build_context is not None
                or self.pending_apply is not None
            ):
                raise RuntimeError("Sestavení nebo aplikování předchozí revize ještě probíhá.")
            cli, project = self._paths()
            pio = find_pio()
            script = project / "scripts/build.py"
            if not pio or not script.is_file():
                raise ValueError("Build vyžaduje PlatformIO a projektový scripts/build.py.")
            if apply_after:
                token = self.token.get().strip() or self._session_token
                if not token and not os.environ.get("WOKWI_CLI_TOKEN"):
                    raise ValueError("Pro aplikování zadejte Wokwi token v záložce Wokwi.")
                self._session_token = token
                self.token.set("")
            revision = source_revision(project)
            self.builder.start(
                [sys.executable, str(script), "--pio", pio, "--wokwi-cli", str(cli)],
                project,
            )
            self.build_context = {
                "project": project,
                "revision": revision,
                "apply": apply_after,
            }
            self.build_lines.clear()
            self.build_status = (
                "Sestavuji uloženou revizi " + revision[:10] + "; dosavadní simulace pokračuje."
            )
        except (OSError, ValueError, RuntimeError, KeyError) as exc:
            self.build_status = str(exc)
            self.status.set(str(exc))

    def poll_build(self):
        for _ in range(100):
            try:
                line = self.builder.logs.get_nowait()
            except queue.Empty:
                break
            self.build_lines.append(line)
            self.runner.log("[build] " + line)
        if self.build_context and not self.builder.busy:
            context = self.build_context
            self.build_context = None
            try:
                if self.builder.state != "completed":
                    raise RuntimeError(
                        f"Sestavení selhalo (kód {self.builder.exit_code}). Běžící firmware nebyl změněn."
                    )
                if source_revision(context["project"]) != context["revision"]:
                    raise RuntimeError(
                        "Zdroj se během sestavení změnil. Nový firmware nebyl aplikován."
                    )
                self.built_revision = context["revision"]
                self.built_artifacts = artifact_revision(context["project"])
                self.build_status = "Sestaveno: " + self.built_revision[:10]
                if context["apply"]:
                    self.pending_apply = context
                    self.await_hardware = False
                    self.app.pause()
                    self.runner.stop()
                    self.build_status += " · čekám na ukončení staré simulace."
            except (OSError, ValueError, RuntimeError, KeyError) as exc:
                self.build_status = str(exc)
        if self.pending_apply and not self.runner.busy and not self.busy and self.job is None:
            context = self.pending_apply
            self.pending_apply = None
            try:
                if (
                    Path(self.project.get()).resolve() != context["project"]
                    or source_revision(context["project"]) != context["revision"]
                    or artifact_revision(context["project"]) != self.built_artifacts
                ):
                    raise RuntimeError(
                        "Projekt, zdroj nebo artefakt se změnil. Sestavte jej znovu."
                    )
                self.mode.set("Živá smyčka motoru")
                if not self.start():
                    raise RuntimeError(self.status.get())
                self.build_status = "Nová verze spuštěna; čekám na platné potvrzení hardware."
            except (OSError, ValueError, RuntimeError, KeyError) as exc:
                self.build_status = str(exc)

    def check_cli(self):
        try:
            cli, project = self._paths()
            self._task(lambda: self.runner.start([str(cli), "--version"], project))
            self.job = "check"
        except (OSError, ValueError, RuntimeError, KeyError) as exc:
            self.status.set(str(exc))

    def stop(self):
        if self.build_context:
            self.build_context["apply"] = False
        self.pending_apply = None
        self.builder.stop()
        self.cancel_operation.set()
        if self.job == "live":
            self.app.pause()
            self.app.engine.invalidate()
        self.await_hardware = False
        self.runner.stop()
        self.status.set("Zastavuji Wokwi…")

    def clear_log(self):
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")
        self.log_rows = 0

    def poll(self):
        if self.closed:
            return
        self.poll_build()
        while True:
            try:
                result, detail = self.results.get_nowait()
            except queue.Empty:
                break
            if result == "error":
                self.runner.stop()
                self.await_hardware = False
                self.operation_error = detail
                self.runner.log("Operace selhala: " + detail)
                self.status.set("Operace selhala: " + detail)
        lines = []
        for _ in range(200):
            try:
                lines.append(self.runner.logs.get_nowait())
            except queue.Empty:
                break
        if lines:
            self.log.configure(state="normal")
            self.log.insert("end", "\n".join(lines) + "\n")
            self.log_rows += len(lines)
            if self.log_rows > 1000:
                self.log.delete("1.0", f"{self.log_rows - 1000 + 1}.0")
                self.log_rows = 1000
            self.log.configure(state="disabled")
            self.log.see("end")
        active = self.busy or self.runner.busy
        for button in (self.start_button, self.check_button):
            button.configure(state="disabled" if active else "normal")
        self.build_button.configure(
            state="disabled"
            if self.builder.busy or self.build_context is not None or self.pending_apply is not None
            else "normal"
        )
        self.stop_button.configure(state="normal" if active or self.builder.busy else "disabled")
        if active and self.runner.stop_event.is_set():
            self.status.set("Zastavuji Wokwi…")
        elif self.job == "live" and not self.busy and self.runner.busy:
            if self.await_hardware and self.app.bridge.metrics["received"] > 0:
                self.app.resume()
                self.hardware_confirmed = True
                self.running_revision = self.launch_revision
                if self.running_revision:
                    self.build_status = (
                        "Nový proces potvrdil komunikaci; předaná revize "
                        + self.running_revision[:10]
                    )
                self.await_hardware = False
                self.status.set(
                    "Živá smyčka · hardware potvrdil komunikaci · model běží rychlostí 1×"
                )
            elif self.await_hardware:
                self.status.set(
                    "CLI běží, ale hardware zatím nepotvrdil komunikaci. Podrobnosti jsou ve výpisu."
                    if monotonic() - self.wait_since > 15
                    else "Wokwi CLI běží · čekám na potvrzení virtuálního hardware…"
                )
        elif self.runner.busy and not self.busy:
            self.status.set(
                {
                    "scenario": "Běží testovací scénář · samostatné vstupní stavy",
                    "build": "Probíhá sestavení",
                    "check": "Ověřuji CLI",
                }.get(self.job, "CLI běží")
            )
        if self.job and not active:
            job = self.job
            self.job = None
            self.await_hardware = False
            cancelled = self.cancel_operation.is_set() or self.runner.state == "stopped"
            label = (
                "Zastaveno"
                if cancelled
                else "Dokončeno"
                if self.runner.state == "completed"
                else "Chyba"
            )
            if not cancelled and self.runner.exit_code == 42:
                label = (
                    "Dosažen časový limit"
                    if job == "live"
                    else "Scénář nebyl dokončen v časovém limitu"
                )
            if job == "live" and not self.hardware_confirmed and not cancelled:
                label = "CLI skončil bez potvrzení virtuálního hardware"
            self.status.set(
                f"{label} · kód {self.runner.exit_code} · ztracené řádky {self.runner.dropped_logs}"
            )
            if self.operation_error:
                self.status.set("Operace selhala: " + self.operation_error)
            if job == "live":
                self.running_revision = None
                self.status.set(self.status.get() + " · model pozastaven; návrat do Mock")
                self.app.pause()
                self._task(lambda: self.app.switch_backend("mock", paused=True))

    def close(self):
        self.closed = True
        self.pending_apply = None
        self.builder.stop()
        self.cancel_operation.set()
        self.await_hardware = False
        self.runner.stop()
        if self.job == "live":
            self.app.pause()
            self.app.engine.invalidate()
        if self.operation is not None:
            self.operation.join(25)
            if self.operation.is_alive():
                raise RuntimeError("Změna backendu se neukončila")
        self.runner.close()
        self.builder.close()
        self._session_token = ""
