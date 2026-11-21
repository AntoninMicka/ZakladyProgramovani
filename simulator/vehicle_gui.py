"""Palubní deska, ovládání auta a monitor lokální CAN; bez vlastního vlákna."""

import math
import tkinter as tk
from tkinter import ttk

BG = "#0f172a"
PANEL = "#1e293b"
TEXT = "#e2e8f0"
SENSOR_LABELS = {
    "wheel_speed_kmh": "Rychlosti kol [km/h]",
    "vehicle_speed_kmh": "Rychlost vozidla [km/h]",
    "intake_air_c": "Teplota nasávaného vzduchu [°C]",
    "barometric_pressure_kpa": "Atmosférický tlak [kPa]",
    "fuel_rail_pressure_kpa": "Tlak palivové lišty [kPa]",
    "exhaust_temp_c": "Teplota výfuku [°C]",
    "steering_deg": "Úhel řízených kol [°]",
    "yaw_rate_deg_s": "Rychlost stáčení [°/s]",
    "longitudinal_accel_m_s2": "Podélné zrychlení [m/s²]",
    "lateral_accel_m_s2": "Příčné zrychlení [m/s²]",
    "brake_pressure_bar": "Tlak brzd jednotlivých kol [bar]",
    "coolant_c": "Chladicí kapalina [°C]",
    "oil_temp_c": "Teplota oleje [°C]",
    "oil_pressure_kpa": "Tlak oleje [kPa]",
    "battery_v": "Napětí palubní sítě [V]",
    "maf_g_s": "Hmotnostní průtok vzduchu [g/s]",
    "fuel_level_l": "Palivo v nádrži [l]",
    "gearbox_input_rpm": "Vstup převodovky [ot/min]",
    "gearbox_output_rpm": "Výstup převodovky [ot/min]",
}


class VehiclePanel:
    def __init__(self, parent, app):
        self.app = app
        self.enabled = tk.BooleanVar(value=app.engine.vehicle is not None)
        toolbar = ttk.Frame(parent)
        toolbar.pack(fill="x")
        ttk.Checkbutton(
            toolbar, text="Zapnout model auta", variable=self.enabled, command=self.toggle
        ).pack(side="left")
        ttk.Label(toolbar, text="Výukový model · přední pohon · virtuální CAN 500 kbit/s").pack(
            side="left", padx=16
        )
        controls = ttk.Frame(parent)
        controls.pack(fill="x", pady=8)
        initial = app.engine.vehicle.snapshot() if app.engine.vehicle is not None else {}
        self.selector = tk.StringVar(value=initial.get("selector", "N"))
        ttk.Label(controls, text="Volič").pack(side="left")
        selector = ttk.Combobox(
            controls,
            textvariable=self.selector,
            values=("P", "R", "N", "D"),
            state="readonly",
            width=4,
        )
        selector.pack(side="left", padx=6)
        selector.bind("<<ComboboxSelected>>", self.command)
        self.brake = tk.DoubleVar(value=initial.get("brake", 0) * 100)
        self.steer = tk.DoubleVar(value=initial.get("steer_deg", 0))
        self.mu_left = tk.DoubleVar(value=initial.get("mu_left", 0.85))
        self.mu_right = tk.DoubleVar(value=initial.get("mu_right", 0.85))
        for label, variable, low, high, resolution in (
            ("Brzda %", self.brake, 0, 100, 1),
            ("Volant °", self.steer, -30, 30, 1),
            ("μ vlevo", self.mu_left, 0.05, 1.2, 0.05),
            ("μ vpravo", self.mu_right, 0.05, 1.2, 0.05),
        ):
            ttk.Label(controls, text=label).pack(side="left", padx=(8, 2))
            tk.Scale(
                controls,
                variable=variable,
                from_=low,
                to=high,
                resolution=resolution,
                orient="horizontal",
                length=125,
                bg=BG,
                fg=TEXT,
                highlightthickness=0,
                command=self.command,
            ).pack(side="left")
        switches = ttk.Frame(parent)
        switches.pack(fill="x")
        self.abs_enabled = tk.BooleanVar(value=True)
        self.esp_enabled = tk.BooleanVar(value=True)
        self.can_enabled = tk.BooleanVar(value=True)
        for title, variable in (
            ("ABS", self.abs_enabled),
            ("ESP", self.esp_enabled),
            ("CAN připojena", self.can_enabled),
        ):
            ttk.Checkbutton(switches, text=title, variable=variable, command=self.command).pack(
                side="left", padx=6
            )
        ttk.Label(switches, text="Pedál plynu ovládáš společným posuvníkem nahoře.").pack(
            side="left", padx=16
        )
        self.status = tk.StringVar(value="Zapni model auta a zvol D pro jízdu.")
        ttk.Label(parent, textvariable=self.status).pack(anchor="w", pady=6)
        self.canvas = tk.Canvas(parent, height=260, bg=BG, highlightthickness=0)
        self.canvas.pack(fill="x")
        pages = ttk.Notebook(parent)
        pages.pack(fill="both", expand=True)
        sensors_page = ttk.Frame(pages)
        can_page = ttk.Frame(pages)
        pages.add(sensors_page, text="Senzory a pohon")
        pages.add(can_page, text="Monitor CAN")
        self.sensors = ttk.Treeview(
            sensors_page, columns=("value",), show="tree headings", height=12
        )
        self.sensors.heading("#0", text="Senzor / veličina")
        self.sensors.heading("value", text="Hodnota")
        self.sensors.column("#0", width=340)
        self.sensors.column("value", width=500)
        scroll = ttk.Scrollbar(sensors_page, orient="vertical", command=self.sensors.yview)
        self.sensors.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.sensors.pack(fill="both", expand=True)
        self.can_summary = tk.StringVar()
        ttk.Label(can_page, textvariable=self.can_summary).pack(anchor="w")
        self.frames = ttk.Treeview(
            can_page, columns=("time", "id", "sender", "hex", "signals"), show="headings", height=12
        )
        for key, title, width in (
            ("time", "Čas [s]", 85),
            ("id", "ID", 65),
            ("sender", "Odesílatel", 100),
            ("hex", "Data [hex]", 180),
            ("signals", "Dekódovaná pole", 420),
        ):
            self.frames.heading(key, text=title)
            self.frames.column(key, width=width, stretch=key == "signals")
        scroll = ttk.Scrollbar(can_page, orient="vertical", command=self.frames.yview)
        self.frames.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.frames.pack(fill="both", expand=True)
        self.last_refresh = -1
        self.last_vehicle_time = -1

    def toggle(self):
        self.app.engine.set_vehicle_enabled(self.enabled.get())
        if self.enabled.get():
            self.command()

    def command(self, _=None):
        if self.app.engine.vehicle is None:
            return
        try:
            self.app.engine.vehicle_command(
                {
                    "selector": self.selector.get(),
                    "brake": self.brake.get() / 100,
                    "steer_deg": self.steer.get(),
                    "mu_left": self.mu_left.get(),
                    "mu_right": self.mu_right.get(),
                    "abs_enabled": self.abs_enabled.get(),
                    "esp_enabled": self.esp_enabled.get(),
                    "can_enabled": self.can_enabled.get(),
                }
            )
        except (ValueError, BufferError) as exc:
            self.status.set(str(exc))

    def gauge(self, cx, cy, radius, value, maximum, title, unit, color):
        c = self.canvas
        c.create_arc(
            cx - radius,
            cy - radius,
            cx + radius,
            cy + radius,
            start=30,
            extent=240,
            style="arc",
            outline="#334155",
            width=12,
        )
        if value is not None:
            angle = math.radians(210 - min(1, max(0, value / maximum)) * 240)
            c.create_line(
                cx,
                cy,
                cx + math.cos(angle) * radius * 0.8,
                cy - math.sin(angle) * radius * 0.8,
                fill=color,
                width=4,
            )
        c.create_text(
            cx,
            cy + 35,
            text="—" if value is None else f"{value:.0f}",
            fill=TEXT,
            font=("Sans", 24, "bold"),
        )
        c.create_text(cx, cy + 65, text=unit, fill="#94a3b8")
        c.create_text(cx, cy - radius - 15, text=title, fill=TEXT, font=("Sans", 12, "bold"))

    def refresh(self, state):
        vehicle = state.get("vehicle")
        self.enabled.set(vehicle is not None)
        self.canvas.delete("all")
        if vehicle is None:
            self.status.set("Režim motoru: zapni model auta pro převodovku, kola, ABS/ESP a CAN.")
            self.sensors.delete(*self.sensors.get_children())
            self.frames.delete(*self.frames.get_children())
            self.can_summary.set("")
            return
        if vehicle["time_us"] < self.last_vehicle_time:
            self.brake.set(vehicle["brake"] * 100)
            self.steer.set(vehicle["steer_deg"])
            self.mu_left.set(vehicle["mu_left"])
            self.mu_right.set(vehicle["mu_right"])
        self.last_vehicle_time = vehicle["time_us"]
        d = vehicle["dashboard"]
        width = max(900, self.canvas.winfo_width())
        self.gauge(width * 0.20, 120, 80, d["speed_kmh"], 180, "RYCHLOST", "km/h", "#38bdf8")
        self.gauge(width * 0.48, 120, 80, d["rpm"], 7500, "OTÁČKY MOTORU", "ot/min", "#4ade80")
        gear = d["gear"]
        gear_text = (
            "—" if gear is None else ("R" if gear == -1 else "N" if gear == 0 else str(gear))
        )
        self.canvas.create_text(
            width * 0.76,
            65,
            text=f"{vehicle['selector']} / {gear_text}",
            fill=TEXT,
            font=("Sans", 32, "bold"),
        )
        self.canvas.create_text(
            width * 0.76, 108, text="ŘAZENÍ" if d["shifting"] else "PŘEVODOVKA", fill="#94a3b8"
        )
        lamps = (
            ("ABS zásah", d["abs"]),
            ("ESP zásah", d["esp"]),
            ("CAN chyba", d["can_fault"]),
            ("Olej", d["oil_kpa"] is not None and d["oil_kpa"] < 60),
            ("Teplota", d["coolant_c"] is not None and d["coolant_c"] > 110),
            ("Dobíjení", d["battery_v"] is not None and d["battery_v"] < 13),
        )
        for i, (title, active) in enumerate(lamps):
            x = width * 0.64 + (i % 3) * 100
            y = 150 + (i // 3) * 40
            self.canvas.create_rectangle(
                x, y, x + 90, y + 28, fill="#f59e0b" if active else PANEL, outline=""
            )
            self.canvas.create_text(x + 45, y + 14, text=title, fill=BG if active else "#94a3b8")

        def number(value, unit):
            return "—" if value is None else f"{value:.1f} {unit}"

        self.canvas.create_text(
            width / 2,
            240,
            text=f"Palivo: {number(d['fuel_pct'], '%')}     Kapalina: {number(d['coolant_c'], '°C')}     Síť: {number(d['battery_v'], 'V')}",
            fill=TEXT,
            font=("Sans", 11),
        )
        self.status.set(
            f"Ujeto {vehicle['distance_m']:.1f} m · zatížení od spojky {vehicle['engine_load_nm']:.1f} Nm · "
            f"ESP moment {vehicle['torque_factor'] * 100:.0f} % · "
            f"ABS {'zapnuto' if vehicle['abs_enabled'] else 'vypnuto'} / ESP {'zapnuto' if vehicle['esp_enabled'] else 'vypnuto'}"
        )
        # Ovládací prvky sledují i reset a změny přes CLI/externí povely.
        self.selector.set(vehicle["selector"])
        self.abs_enabled.set(vehicle["abs_enabled"])
        self.esp_enabled.set(vehicle["esp_enabled"])
        self.can_enabled.set(vehicle["can"]["enabled"])
        now = state["time_s"]
        if now >= self.last_refresh and now - self.last_refresh < 0.2:
            return
        self.last_refresh = now
        self.sensors.delete(*self.sensors.get_children())
        for key, value in vehicle["sensors"].items():
            if isinstance(value, dict):
                value = " · ".join(f"{k}: {v:.2f}" for k, v in value.items())
            elif isinstance(value, float):
                value = f"{value:.3f}"
            self.sensors.insert("", "end", text=SENSOR_LABELS.get(key, key), values=(value,))
        self.frames.delete(*self.frames.get_children())
        bus = vehicle["can"]
        self.can_summary.set(
            f"{bus['bitrate'] / 1000:g} kbit/s · doručeno {bus['delivered']} · "
            f"zahozeno {bus['dropped']} · fronta {bus['queue_depth']} · vytížení {bus['utilization_pct']:.1f} %"
        )
        for frame in bus["frames"][-50:]:
            self.frames.insert(
                "",
                "end",
                values=(
                    f"{frame['time_us'] / 1e6:.3f}",
                    f"0x{frame['id']:03X}",
                    frame["sender"],
                    frame["hex"],
                    ", ".join(f"{k}={v}" for k, v in frame["signals"].items()),
                ),
            )
        children = self.frames.get_children()
        if children:
            self.frames.see(children[-1])
