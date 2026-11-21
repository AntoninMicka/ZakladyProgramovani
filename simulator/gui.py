"""Živý Tk pohled. Model i komunikační worker zůstávají mimo GUI vlákno."""

from collections import deque
import math
from time import monotonic
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path
from telemetry import TelemetryBuffer
from visualization import cylinder_phase, piston_position
from wokwi_gui import WokwiPanel
from ecu_editor import EcuEditor
from engine_diagram import EngineDiagram
from vehicle_gui import VehiclePanel
from vehicle_diagram import VehicleDiagram
from driving_gui import DrivingPanel

BG = "#0f172a"
PANEL = "#1e293b"
TEXT = "#e2e8f0"
MUTED = "#94a3b8"
PHASES = (
    ("SÁNÍ", "#38bdf8"),
    ("KOMPRESE", "#a78bfa"),
    ("EXPANZE", "#fb923c"),
    ("VÝFUK", "#4ade80"),
)


class EngineView:
    def __init__(self, root, app, rate=20, on_frame=None, duration=None):
        self.root, self.app = root, app
        self.interval = max(10, round(1000 / rate))
        self.on_frame, self.duration = on_frame, duration
        self.started = monotonic()
        self.history = deque(maxlen=600)
        self.closed = False
        self.last_time = -1
        self.last_frame = None
        self.telemetry = TelemetryBuffer()
        self.next_telemetry_wall = 0.0
        self.log_rows = 0
        root.title("ECU Simulator · motor a auto")
        root.geometry("1180x940")
        root.minsize(960, 760)
        root.configure(bg=BG)
        root.protocol("WM_DELETE_WINDOW", self.request_close)
        style = ttk.Style(root)
        style.theme_use("clam")
        style.configure("TFrame", background=BG)
        style.configure("TLabel", background=BG, foreground=TEXT)
        style.configure("TButton", padding=7)
        header = ttk.Frame(root, padding=(18, 12))
        header.pack(fill="x")
        ttk.Label(header, text="ECU / MOTOR", font=("Sans", 21, "bold")).pack(side="left")
        self.status = tk.StringVar(value="Spouštím…")
        ttk.Label(header, textvariable=self.status).pack(side="right")
        controls = ttk.Frame(root, padding=(18, 0, 18, 8))
        controls.pack(fill="x")
        self.pause_button = ttk.Button(controls, text="Pozastavit", command=self.toggle_pause)
        self.pause_button.pack(side="left", padx=(0, 12))
        state = app.engine.snapshot()
        self.throttle = tk.DoubleVar(value=state["throttle"] * 100)
        self.load = tk.DoubleVar(value=state["load_nm"])
        self.speed = tk.StringVar(value=f"{app.engine.speed:g}")
        for title, variable, maximum in [
            ("Pedál %", self.throttle, 100),
            ("Zátěž Nm", self.load, 100),
        ]:
            ttk.Label(controls, text=title).pack(side="left", padx=(0, 4))
            tk.Scale(
                controls,
                variable=variable,
                from_=0,
                to=maximum,
                orient="horizontal",
                length=150,
                bg=BG,
                fg=TEXT,
                highlightthickness=0,
                troughcolor=PANEL,
                command=self.command,
            ).pack(side="left", padx=(0, 12))
        ttk.Label(controls, text="Rychlost simulace").pack(side="left", padx=(0, 6))
        speeds = ttk.Combobox(
            controls,
            textvariable=self.speed,
            values=("1", "0.2", "0.05", "0.02"),
            state="readonly",
            width=6,
        )
        speeds.pack(side="left")
        speeds.bind("<<ComboboxSelected>>", self.change_speed)
        ttk.Label(controls, text="× wall time").pack(side="left", padx=6)
        notebook = ttk.Notebook(root)
        notebook.pack(fill="both", expand=True, padx=12)
        body = ttk.Frame(notebook)
        notebook.add(body, text="Motor")
        telemetry_page = ttk.Frame(notebook, padding=10)
        notebook.add(telemetry_page, text="Telemetrie")
        self.notebook = notebook
        self.build_telemetry(telemetry_page)
        wokwi_page = ttk.Frame(notebook, padding=12)
        notebook.add(wokwi_page, text="Wokwi")
        self.wokwi_panel = WokwiPanel(wokwi_page, app)
        editor_page = ttk.Frame(notebook, padding=10)
        notebook.add(editor_page, text="Editor ECU")
        self.ecu_editor = EcuEditor(
            editor_page, self.wokwi_panel, lambda: notebook.select(wokwi_page)
        )
        self.diagram_page = ttk.Frame(notebook, padding=10)
        notebook.add(self.diagram_page, text="Schéma motoru / vozu")
        self.diagram_tabs = ttk.Notebook(self.diagram_page)
        self.diagram_tabs.pack(fill="both", expand=True)
        self.engine_drawing_page = ttk.Frame(self.diagram_tabs, padding=6)
        self.car_drawing_page = ttk.Frame(self.diagram_tabs, padding=6)
        self.diagram_tabs.add(self.car_drawing_page, text="Celý vůz")
        self.diagram_tabs.add(self.engine_drawing_page, text="Řez motoru")
        self.engine_diagram = EngineDiagram(self.engine_drawing_page, app)
        self.vehicle_diagram = VehicleDiagram(self.car_drawing_page, app)
        self.diagram_tabs.select(
            self.car_drawing_page if app.engine.vehicle is not None else self.engine_drawing_page
        )
        self.vehicle_page = ttk.Frame(notebook, padding=10)
        notebook.add(self.vehicle_page, text="Auto / palubní deska")
        self.vehicle_panel = VehiclePanel(self.vehicle_page, app)
        if app.engine.vehicle is not None:
            notebook.select(self.vehicle_page)
        self.driving_page = ttk.Frame(notebook, padding=10)
        notebook.add(self.driving_page, text="Jízda / okruh")
        self.driving_panel = DrivingPanel(self.driving_page, app)
        if app.engine.driving is not None:
            notebook.select(self.driving_page)
        scrollbar = ttk.Scrollbar(body, orient="vertical")
        scrollbar.pack(side="right", fill="y")
        self.canvas = tk.Canvas(body, bg=BG, highlightthickness=0, yscrollcommand=scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        scrollbar.configure(command=self.canvas.yview)
        footer = ttk.Frame(root, padding=(18, 8, 18, 12))
        footer.pack(fill="x", side="bottom", before=notebook)
        self.display_hint = tk.StringVar(
            value="Fáze válců = kinematické schéma. Pro čitelný pohyb zvolte rychlost 0.02×."
        )
        ttk.Label(footer, textvariable=self.display_hint, foreground=MUTED).pack(anchor="w")
        ttk.Label(
            footer,
            text="CKP/CMP = vzor podle úhlu hostitele; přesnost pinů Wokwi tím není měřena.",
            foreground=MUTED,
        ).pack(anchor="w")
        self.timer = root.after(0, self.refresh)

    def build_telemetry(self, page):
        toolbar = ttk.Frame(page)
        toolbar.pack(fill="x", pady=(0, 8))
        self.log_summary = tk.StringVar(value="Čekám na první vzorek…")
        ttk.Label(toolbar, textvariable=self.log_summary).pack(side="left")
        ttk.Button(toolbar, text="Vymazat výpis", command=self.clear_telemetry).pack(side="right")
        ttk.Button(toolbar, text="Uložit záznamy…", command=self.save_telemetry).pack(
            side="right", padx=8
        )
        self.autoscroll = tk.BooleanVar(value=True)
        ttk.Checkbutton(toolbar, text="Sledovat konec", variable=self.autoscroll).pack(
            side="right", padx=8
        )
        ttk.Label(page, text="Aktuální snímek · snímače, výstupy ECU a diagnostika").pack(
            anchor="w"
        )
        self.current_telemetry = tk.Text(
            page,
            height=14,
            bg=PANEL,
            fg=TEXT,
            wrap="none",
            font=("Monospace", 10),
            state="disabled",
        )
        self.current_telemetry.pack(fill="x", pady=(4, 12))
        ttk.Label(
            page,
            text="Průběžný výpis · nejvýše 5 vzorků/s wall time · posledních 1000 vzorků",
        ).pack(anchor="w")
        log_frame = ttk.Frame(page)
        log_frame.pack(fill="both", expand=True, pady=(4, 0))
        vertical = ttk.Scrollbar(log_frame, orient="vertical")
        horizontal = ttk.Scrollbar(log_frame, orient="horizontal")
        self.telemetry_log = tk.Text(
            log_frame,
            bg=PANEL,
            fg="#86efac",
            wrap="none",
            font=("Monospace", 10),
            height=12,
            state="disabled",
            xscrollcommand=horizontal.set,
            yscrollcommand=vertical.set,
        )
        self.telemetry_log.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        vertical.configure(command=self.telemetry_log.yview)
        horizontal.configure(command=self.telemetry_log.xview)
        log_frame.rowconfigure(0, weight=1)
        log_frame.columnconfigure(0, weight=1)

    def update_telemetry(self, state, diagnostics):
        wall = monotonic() - self.started
        if wall < self.next_telemetry_wall:
            return
        self.next_telemetry_wall = wall + 0.2
        line = self.telemetry.append(state, diagnostics, wall)
        levels, d = state["signal_levels"], state["diagnostics"]
        current = (
            f"Wall čas: {wall:.3f} s    Simulační čas: {state['time_s']:.6f} s    Pauza: {state['paused']}\n"
            f"RPM: {state['rpm']:.1f}    Klika: {state['crank_angle_deg']:.2f}°    Cyklus: {state['cycle_angle_deg']:.2f}°\n"
            f"TPS: {100 * state['tps']:.1f} %    MAP: {state['map_kpa']:.2f} kPa    Lambda: {state['lambda_value']:.3f}\n"
            f"IAT: {state['iat_c']:.1f} °C    CLT: {state['clt_c']:.1f} °C    Zátěž: {state['load_nm']:.2f} Nm\n"
            f"Dávka: {state['injector_ms']:.3f} ms    Předstih: {state['ignition_deg']:.2f}°    CKP/CMP: {levels['CKP']}/{levels['CMP']}\n"
            f"Aktivní vstřikovače: {state['injector_active']}    Nabíjené cívky: {state['coil_charging']}\n"
            f"Poslední vstřikovací pulzy [µs]: {state['last_injection_us']}\n"
            f"Poslední dwell [µs]: {state['last_dwell_us']}\n"
            f"Linka: {diagnostics.get('connected', 'mock')}    Přijato: {diagnostics['received']}    Neplatné zprávy: {diagnostics['invalid']}\n"
            f"RTT [µs]: {diagnostics.get('rtt_us')}    Offset ECU [µs]: {diagnostics.get('ecu_offset_us')}    Drift [µs]: {diagnostics.get('ecu_drift_us')}\n"
            f"Ztracené hrany: {d['dropped_events']}    Pozdní události: {d['late_events']}    Chybné povely: {d['rejected_commands']}\n"
            f"Max. zpoždění [µs]: {d['max_lateness_us']}    Max. wall lag [µs]: {d['max_wall_lag_us']}"
        )
        hardware = diagnostics.get("hardware")
        if hardware:
            current += (
                f"\nVirtuální hardware: {'BĚH' if hardware['running'] else 'ZASTAVEN'}    "
                f"Buffer: {hardware['queue_depth']}    Fázová odchylka: {hardware['phase_error_deg']:.3f}°"
                f"\nHW pozdní aktualizace: {hardware['late_updates']}    CRC chyby: {hardware['crc_errors']}    "
                f"Ztracené zprávy: {hardware['dropped_tx']}    Watchdog: {hardware['watchdog_timeouts']}"
            )
        self.current_telemetry.configure(state="normal")
        self.current_telemetry.delete("1.0", "end")
        self.current_telemetry.insert("end", current)
        self.current_telemetry.configure(state="disabled")
        self.telemetry_log.configure(state="normal")
        self.telemetry_log.insert("end", line + "\n")
        self.log_rows += 1
        if self.log_rows > self.telemetry.samples.maxlen:
            self.telemetry_log.delete("1.0", "2.0")
            self.log_rows -= 1
        self.telemetry_log.configure(state="disabled")
        if self.autoscroll.get():
            self.telemetry_log.see("end")
        self.log_summary.set(
            f"Uloženo v paměti: {len(self.telemetry.samples)} / {self.telemetry.total} vzorků"
        )

    def clear_telemetry(self):
        self.telemetry.clear()
        self.log_rows = 0
        self.telemetry_log.configure(state="normal")
        self.telemetry_log.delete("1.0", "end")
        self.telemetry_log.configure(state="disabled")
        self.log_summary.set("Výpis vymazán · soubor --telemetry pokračuje")
        self.next_telemetry_wall = 0

    def export_telemetry(self, path):
        path = Path(path)
        content = self.telemetry.text() if path.suffix.lower() == ".txt" else self.telemetry.jsonl()
        path.write_text(content, encoding="utf-8")

    def save_telemetry(self):
        path = filedialog.asksaveasfilename(
            parent=self.root,
            title="Uložit poslední vzorky telemetrie",
            defaultextension=".jsonl",
            initialfile="ecu-telemetrie.jsonl",
            filetypes=[
                ("JSON Lines – úplné vzorky", "*.jsonl"),
                ("Textový výpis", "*.txt"),
            ],
        )
        if path:
            try:
                self.export_telemetry(path)
            except OSError as exc:
                messagebox.showerror("Telemetrii se nepodařilo uložit", str(exc), parent=self.root)

    def command(self, _=None):
        try:
            self.app.engine.command(
                {"throttle": self.throttle.get() / 100, "load_nm": self.load.get()}
            )
        except BufferError:
            self.status.set("Fronta povelů je plná — zkuste změnu znovu")

    def change_speed(self, _=None):
        self.app.engine.set_speed(float(self.speed.get()))

    def toggle_pause(self):
        if self.app.engine.driving is not None:
            self.notebook.select(self.driving_page)
            self.driving_panel.toggle_pause()
            return
        if self.app.engine.snapshot()["paused"]:
            self.app.resume()
            self.pause_button.configure(text="Pozastavit")
        else:
            self.app.pause()
            self.pause_button.configure(text="Pokračovat")

    def request_close(self):
        if self.ecu_editor.confirm_discard():
            self.close()
        else:
            self.duration = None

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.ecu_editor.close()
        self.driving_panel.close()
        try:
            self.root.after_cancel(self.timer)
            self.root.destroy()
        except tk.TclError:
            pass
        finally:
            self.wokwi_panel.close()

    def text(self, x, y, text, size=12, color=TEXT, anchor="nw", bold=False):
        return self.canvas.create_text(
            x,
            y,
            text=text,
            fill=color,
            anchor=anchor,
            font=("Sans", size, "bold" if bold else "normal"),
        )

    def refresh(self):
        if self.closed:
            return
        if self.duration is not None and monotonic() - self.started >= self.duration:
            self.request_close()
            if self.closed:
                return
        try:
            self.wokwi_panel.poll()
            self.ecu_editor.poll()
            self.driving_panel.poll_input(self.notebook.select() == str(self.driving_page))
            frame = (
                {"type": "sensors", **self.app.engine.snapshot()}
                if self.wokwi_panel.busy
                else self.app.bridge.tick()
            )
            diagnostics = self.app.bridge.diagnostics()
            if self.on_frame:
                self.on_frame(frame, diagnostics)
            if frame["simulation_time_us"] < self.last_time:
                self.history.clear()
            if not self.history or frame["time_s"] - self.history[-1][0] >= 0.02:
                self.history.append((frame["time_s"], frame["rpm"]))
            self.last_time = frame["simulation_time_us"]
            self.last_frame = frame
            self.pause_button.configure(text="Pokračovat" if frame["paused"] else "Pozastavit")
            current_speed = f"{self.app.engine.speed:g}"
            if self.speed.get() != current_speed:
                self.speed.set(current_speed)
            self.update_telemetry(frame, diagnostics)
            if self.notebook.select() == str(self.driving_page):
                self.driving_panel.refresh(frame)
            if self.notebook.select() == str(self.vehicle_page):
                self.vehicle_panel.refresh(frame)
            if self.notebook.select() == str(self.diagram_page):
                self.engine_diagram.refresh(frame, diagnostics)
                self.vehicle_diagram.refresh(frame, diagnostics)
            link = (
                "MOCK · bez Wokwi"
                if self.app.mode == "mock"
                else (
                    "WOKWI · připojeno" if diagnostics["connected"] else "WOKWI · čekám na spojení"
                )
            )
            self.display_hint.set(
                "Wokwi má vlastní hodiny. Pauza a rychlost ovládají pouze model v Pythonu."
                if self.app.mode == "wokwi"
                else "Fáze válců = kinematické schéma. Pro čitelný pohyb zvolte rychlost 0.02×."
            )
            self.status.set(
                f"{'PAUZA' if frame['paused'] else 'BĚH'}   |   {link}   |   sim {frame['time_s']:.3f} s"
            )
            self.draw(frame, diagnostics)
        except Exception:
            # Žádná skrytá chyba Tk callbacku s ponechaným běžícím modelem.
            self.close()
            raise
        if not self.closed:
            self.timer = self.root.after(self.interval, self.refresh)

    def draw(self, state, diagnostics):
        c = self.canvas
        c.delete("all")
        width = max(936, c.winfo_width())
        metrics = [
            ("OTÁČKY", f"{state['rpm']:.0f}", "RPM"),
            ("MAP", f"{state['map_kpa']:.1f}", "kPa"),
            ("LAMBDA", f"{state['lambda_value']:.2f}", "λ"),
            ("VSTŘIKOVÁNÍ", f"{state['injector_ms']:.2f}", "ms"),
            (
                "KLIKA / CYKLUS",
                f"{state['crank_angle_deg']:.0f} / {state['cycle_angle_deg']:.0f}",
                "°",
            ),
        ]
        cell = width / len(metrics)
        for i, (label, value, unit) in enumerate(metrics):
            x = i * cell + 6
            c.create_rectangle(x, 6, x + cell - 12, 94, fill=PANEL, outline="")
            self.text(x + 14, 16, label, 10, MUTED)
            self.text(x + 14, 39, value, 25, bold=True)
            self.text(x + cell - 26, 72, unit, 10, MUTED, anchor="ne")
        self.text(12, 108, "VÁLCE / ČTYŘTAKT", 12, bold=True)
        self.text(
            width - 12,
            108,
            "Pořadí 1–3–4–2" if state["cylinders"] == 4 else "Rovnoměrné fáze",
            10,
            MUTED,
            anchor="ne",
        )
        # Maximálně 8 válců na řádek, další řádek pro konfigurovatelný 16válec.
        count = state["cylinders"]
        rows = math.ceil(count / 8)
        row_height = 250 if rows == 1 else 180
        cols = min(count, 8)
        for i in range(count):
            phase = cylinder_phase(state["cycle_angle_deg"], i, count)
            label, color = PHASES[int(phase // 180)]
            col, row = i % 8, i // 8
            x = (col + 0.5) * width / cols
            y = 160 + row * row_height
            chamber_width = min(95, width / cols - 36)
            left, right = x - chamber_width / 2, x + chamber_width / 2
            travel = 65 if rows == 1 else 35
            piston_y = y + 25 + piston_position(phase) * travel
            c.create_rectangle(
                left,
                y + 10,
                right,
                y + travel + 45,
                fill=PANEL,
                outline="#64748b",
                width=2,
            )
            c.create_rectangle(left + 3, y + 12, right - 3, piston_y - 7, fill=color, outline="")
            c.create_rectangle(
                left + 2,
                piston_y - 7,
                right - 2,
                piston_y + 7,
                fill="#cbd5e1",
                outline="",
            )
            # Klika a ojnice mají stejnou geometrii jako poloha pístu.
            radius = travel / 2
            center_y = y + 25 + 4.5 * radius
            crank_x = x + radius * math.sin(math.radians(phase))
            crank_y = center_y - radius * math.cos(math.radians(phase))
            c.create_oval(
                x - radius,
                center_y - radius,
                x + radius,
                center_y + radius,
                outline="#475569",
            )
            c.create_line(x, piston_y, crank_x, crank_y, fill="#cbd5e1", width=4)
            c.create_line(x, center_y, crank_x, crank_y, fill=color, width=5)
            c.create_oval(
                crank_x - 4,
                crank_y - 4,
                crank_x + 4,
                crank_y + 4,
                fill=color,
                outline="",
            )
            self.text(x, y - 12, f"VÁLEC {i + 1}", 10, anchor="n", bold=True)
            self.text(x, y + row_height - 24, label, 10, color, anchor="n", bold=True)
        signal_y = 160 + rows * row_height
        self.text(12, signal_y, "SNÍMAČE / ÚHLOVÝ VZOR 0–720°", 12, bold=True)
        left, right = 62, width - 18
        span = right - left
        cursor = left + state["cycle_angle_deg"] / 720 * span
        for index, name in enumerate(("CKP", "CMP")):
            baseline = signal_y + 50 + index * 43
            self.text(12, baseline - 12, name, 10, MUTED)
            points = []
            # Dva vzorky na každý půlstupeň: schematický vzor, ne osciloskop.
            for angle, levels in self.app.engine.signals.plot_samples:
                level = levels[name]
                points.extend((left + angle / 720 * span, baseline - 18 * level))
            c.create_line(*points, fill="#38bdf8" if name == "CKP" else "#a78bfa", width=1.5)
            c.create_line(cursor, baseline - 24, cursor, baseline + 7, fill="#fbbf24", width=2)
        for angle in (0, 180, 360, 540, 720):
            self.text(
                left + angle / 720 * span,
                signal_y + 101,
                str(angle) + "°",
                9,
                MUTED,
                anchor="n",
            )
        graph_y = signal_y + 137
        self.text(12, graph_y, "OTÁČKY / SIMULAČNÍ ČAS · OKNO DO 10 s", 11, bold=True)
        top, bottom = graph_y + 28, graph_y + 112
        c.create_rectangle(left, top, right, bottom, fill=PANEL, outline="")
        max_rpm = max(1500, max((rpm for _, rpm in self.history), default=0) * 1.15)
        self.text(12, top, f"{max_rpm:.0f}", 9, MUTED)
        self.text(28, bottom - 12, "0", 9, MUTED)
        now = state["time_s"]
        window = min(10, max(0.1, now))
        self.text(left, bottom + 2, f"{max(0, now - window):.2f} s", 8, MUTED)
        self.text(right, bottom + 2, f"{now:.2f} s", 8, MUTED, anchor="ne")
        points = []
        for t, rpm in self.history:
            if now - window <= t <= now:
                points.extend(
                    (
                        right - (now - t) / window * span,
                        bottom - rpm / max_rpm * (bottom - top),
                    )
                )
        if len(points) >= 4:
            c.create_line(*points, fill="#4ade80", width=2)
        info_y = bottom + 22
        fixed = "STOLICE · pevné RPM" if state["fixed_rpm"] is not None else "VOLNÁ DYNAMIKA"
        self.text(
            12,
            info_y,
            f"{fixed}  |  zátěž {state['load_nm']:.1f} Nm  |  CLT {state['clt_c']:.0f} °C  |  IAT {state['iat_c']:.0f} °C",
            10,
            MUTED,
        )
        self.text(
            12,
            info_y + 22,
            f"Ztracené hrany: {state['diagnostics']['dropped_events']}   ·   pozdní ECU události: {state['diagnostics']['late_events']}   ·   chybné povely: {state['diagnostics']['rejected_commands']}",
            10,
            MUTED,
        )
        if self.app.mode == "mock":
            ecu = diagnostics.get("controller", {})
            detail = f"Mock · společná C++ ECU · synchronizace {ecu.get('synced', False)} · revize {ecu.get('revision', '—')[:10]} · pulzy {ecu.get('events', 0)}"
        else:
            detail = f"Aktivní vstřikovače: {state['injector_active']}   ·   nabíjené cívky: {state['coil_charging']}   ·   RTT: {diagnostics['rtt_us']} µs"
        self.text(12, info_y + 44, detail, 10, MUTED)
        c.configure(scrollregion=c.bbox("all"))


def run_gui(app, rate=20, on_frame=None, duration=None):
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        raise RuntimeError(
            f"Nelze otevřít grafický displej. Spusťte --gui v desktopovém terminálu. {exc}"
        ) from exc
    # Tk callback chybu předáme ven, aby main uzavřel Engine i transport.
    errors = []

    def failed(_kind, value, traceback):
        errors.append(value.with_traceback(traceback))
        try:
            root.destroy()
        except tk.TclError:
            pass

    root.report_callback_exception = failed
    view = EngineView(root, app, rate, on_frame, duration)
    try:
        root.mainloop()
    finally:
        view.close()
    if errors:
        raise errors[0]
