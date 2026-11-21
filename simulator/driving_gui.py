"""Tk režim jízdy: okruh shora, joypad/klávesnice a nastavení mapování."""

import json
import math
import tkinter as tk
from dataclasses import asdict
from time import monotonic
from tkinter import filedialog, messagebox, ttk

from cockpit import CockpitView
from joypad import AXIS_NAMES, Joypad, Mapping, controls
from racetrack import Circuit


class DrivingPanel:
    def __init__(self, parent, app):
        self.app, self.parent = app, parent
        self.track = Circuit()
        self.keys = set()
        self.key_steer = 0.0
        self.last_poll = monotonic()
        self.last_active = False
        self.check_dialog = None
        self.mapping = getattr(app, "joypad_mapping", Mapping())
        self.mapping_manual = getattr(app, "joypad_mapping_manual", False)
        self.profile_error = ""
        self.profile_note = (
            "Ruční profil" if self.mapping_manual else "Čekám na rozpoznání ovladače"
        )
        self.joypad = Joypad(getattr(app, "joypad_device", "/dev/input/js0"))
        self.source = tk.StringVar(value="Joypad" if Joypad.devices() else "Klávesnice")
        self.device = tk.StringVar(value=self.joypad.device)
        toolbar = ttk.Frame(parent)
        toolbar.pack(fill="x")
        ttk.Button(toolbar, text="Zapnout jízdu / návrat na start", command=self.enable).pack(
            side="left"
        )
        self.pause_button = ttk.Button(toolbar, text="Pokračovat", command=self.toggle_pause)
        self.pause_button.pack(side="left", padx=6)
        ttk.Label(toolbar, text="Ovládání:").pack(side="left", padx=6)
        source = ttk.Combobox(
            toolbar,
            textvariable=self.source,
            values=("Joypad", "Klávesnice"),
            state="readonly",
            width=11,
        )
        source.pack(side="left")
        source.bind("<<ComboboxSelected>>", self.change_source)
        self.view = tk.StringVar(value="Z čelního okna")
        ttk.Combobox(
            toolbar,
            textvariable=self.view,
            values=("Z čelního okna", "Mapa okruhu"),
            state="readonly",
            width=18,
        ).pack(side="right", padx=6)
        self.follow = tk.BooleanVar(value=False)
        ttk.Checkbutton(toolbar, text="Kamera za vozem", variable=self.follow).pack(side="right")
        devices = ttk.Frame(parent)
        devices.pack(fill="x", pady=6)
        ttk.Label(devices, text="Joypad:").pack(side="left")
        self.device_picker = ttk.Combobox(
            devices, textvariable=self.device, values=Joypad.devices(), width=25
        )
        self.device_picker.pack(side="left", padx=6)
        ttk.Button(devices, text="Připojit / obnovit", command=self.connect).pack(side="left")
        ttk.Button(devices, text="Rozpoznat ovladač", command=self.auto_map).pack(
            side="left", padx=6
        )
        ttk.Button(devices, text="Mapování os a tlačítek…", command=self.edit_mapping).pack(
            side="left", padx=6
        )
        ttk.Button(devices, text="Uložit diagnostiku…", command=self.save_diagnostics).pack(
            side="left", padx=6
        )
        checks = ttk.Frame(parent)
        checks.pack(fill="x")
        ttk.Button(checks, text="Ověřit páčky a tlačítka…", command=self.open_check).pack(
            side="left", padx=6
        )
        self.input_status = tk.StringVar(
            value="Klávesnice dostupná; joypad lze připojit tlačítkem."
        )
        ttk.Label(parent, textvariable=self.input_status, wraplength=1050).pack(anchor="w")
        self.mapped_status = tk.StringVar()
        ttk.Label(parent, textvariable=self.mapped_status, wraplength=1050).pack(anchor="w")
        ttk.Label(
            parent,
            text="Šipky / WASD: plyn, brzda, řízení · mezerník: brzda · Enter/P: pauza · R: restart · E: D · Q: R · N: neutrál",
        ).pack(anchor="w", pady=4)
        self.status = tk.StringVar(value="Zapni režim jízdy. Před rozjezdem klikni do okruhu.")
        ttk.Label(parent, textvariable=self.status).pack(anchor="w")
        self.canvas = tk.Canvas(parent, bg="#244d36", highlightthickness=0, takefocus=True)
        self.canvas.pack(fill="both", expand=True, pady=(6, 0))
        self.cockpit = CockpitView(self.canvas, self.track)
        self.canvas.bind("<Button-1>", lambda event: self.canvas.focus_set())
        self.canvas.bind("<KeyPress>", self.key_down)
        self.canvas.bind("<KeyRelease>", self.key_up)
        self.canvas.bind("<FocusOut>", self.canvas_focus_lost)
        parent.winfo_toplevel().bind("<FocusOut>", self.window_focus_lost, add="+")
        if Joypad.devices():
            self.joypad.open()
            self.adopt_mapping()

    def enable(self):
        self.keys.clear()
        self.key_steer = 0
        self.app.engine.enable_driving()
        self.canvas.focus_set()

    def pause(self, reason):
        self.keys.clear()
        self.key_steer = 0
        self.app.engine.pause_driving(reason)
        self.status.set(reason)

    def toggle_pause(self):
        engine = self.app.engine
        if engine.driving is None:
            self.enable()
        if not engine.snapshot()["paused"] and engine.driving.armed:
            self.pause("Jízda pozastavena")
            return
        if self.source.get() == "Joypad":
            self.joypad.poll()
            if self.profile_error and not self.mapping_manual:
                self.pause(self.profile_error)
                return
            if not self.joypad.ready(self.mapping):
                self.pause(
                    "Joypad není připraven: připoj jej a ověř čísla os, nebo zvol klávesnici."
                )
                return
        if self.source.get() == "Joypad" and not self.joypad.neutral(self.mapping):
            self.pause(
                "Před pokračováním uvolni plyn, brzdu a vystřeď řízení. Zkontroluj přepočtené hodnoty."
            )
            return
        self.canvas.focus_set()
        self.send_input()
        engine.resume_driving()

    def connect(self):
        self.pause("Změna připojení joypadu; pokračování potvrď tlačítkem.")
        self.device_picker.configure(values=Joypad.devices())
        self.joypad.close()
        self.joypad = Joypad(self.device.get())
        self.joypad.open()
        self.adopt_mapping()
        self.source.set("Joypad")

    def adopt_mapping(self):
        if self.mapping_manual:
            self.profile_note = "Ruční profil"
            return
        if self.joypad.detected_mapping is not None:
            self.mapping = self.joypad.detected_mapping
            self.profile_error = ""
            self.profile_note = self.joypad.layout
        else:
            self.profile_error = self.joypad.layout
            self.profile_note = self.profile_error

    def auto_map(self):
        self.pause("Rozpoznání ovladače; před pokračováním uvolni pedály.")
        self.mapping_manual = False
        if self.joypad.fd is not None:
            self.joypad.read_layout()
        self.adopt_mapping()

    def open_check(self):
        if self.check_dialog is not None:
            self.check_dialog.window.lift()
            return
        self.pause("Ověřování ovladače; jízdní akce jsou pozastavené.")
        if self.joypad.fd is None or not self.joypad.poll():
            messagebox.showerror(
                "Ovladač není připojen", "Nejprve vyber a připoj ovladač.", parent=self.parent
            )
            return
        from gamepad_check_gui import GamepadCheckDialog

        def closed():
            self.check_dialog = None
            self.joypad.pressed.clear()

        self.check_dialog = GamepadCheckDialog(self.parent, self.joypad, closed)

    def change_source(self, _=None):
        self.pause("Ovládání změněno. Pokračování potvrď tlačítkem.")
        if self.source.get() == "Joypad" and self.joypad.fd is None:
            self.joypad.open()
            self.adopt_mapping()

    def canvas_focus_lost(self, _=None):
        self.keys.clear()
        if (
            self.source.get() == "Klávesnice"
            and self.app.engine.driving is not None
            and self.app.engine.driving.armed
        ):
            self.pause("Klávesnice ztratila zaměření; klikni do okruhu a pokračuj.")

    def window_focus_lost(self, _=None):
        def check():
            driving = self.app.engine.driving
            if driving is None or not driving.armed:
                return
            try:
                if not self.parent.winfo_exists():
                    return
                root = self.parent.winfo_toplevel()
                # focus_displayof() převádí Tcl cestu na Python widget. Interní
                # okno Comboboxu (.popdown) ale v Python children není: KeyError.
                # Potřebujeme pouze vědět, zda má aplikace fokus, nikoli widget.
                focused = root.tk.call("focus", "-displayof", root._w)
            except tk.TclError:
                # Odložená kontrola může doběhnout při zavírání okna.
                return
            if not focused:
                self.pause("Okno ztratilo zaměření. Jízda pozastavena.")

        self.parent.after_idle(check)

    def key_down(self, event):
        key = event.keysym.lower()
        if key not in self.keys:
            if key in ("return", "p"):
                self.toggle_pause()
            elif key == "r":
                self.app.engine.reset()
                self.keys.clear()
            elif key in ("e", "q", "n") and self.app.engine.vehicle is not None:
                self.app.engine.vehicle_command({"selector": {"e": "D", "q": "R", "n": "N"}[key]})
        self.keys.add(key)
        return "break"

    def key_up(self, event):
        self.keys.discard(event.keysym.lower())
        return "break"

    def send_input(self):
        if self.source.get() == "Joypad":
            values = controls(self.joypad.axes, self.mapping, self.joypad.buttons)
            source = "joypad"
        else:
            elapsed = min(0.1, max(0, monotonic() - self.last_poll))
            direction = int(bool(self.keys & {"left", "a"})) - int(bool(self.keys & {"right", "d"}))
            target = float(direction)
            rate = 2.5 if direction == 0 else 1.8
            difference = target - self.key_steer
            self.key_steer += max(-rate * elapsed, min(rate * elapsed, difference))
            values = {
                "throttle": float(bool(self.keys & {"up", "w"})),
                "brake": float(bool(self.keys & {"down", "s", "space"})),
                "steer_deg": self.key_steer * 30,
            }
            source = "keyboard"
        self.app.engine.drive_input(**values, source=source)

    def poll_input(self, active):
        connected = self.joypad.poll()
        if self.check_dialog is not None:
            self.check_dialog.update(self.joypad, connected)
            self.last_poll = monotonic()
            return
        engine = self.app.engine
        if self.source.get() == "Joypad":
            raw = ", ".join(
                f"{i}/{AXIS_NAMES.get(self.joypad.axis_codes[i], '?') if i < len(self.joypad.axis_codes) else '?'}:{v:+.2f}"
                for i, v in sorted(self.joypad.axes.items())
            )
            buttons = ",".join(str(i) for i, value in self.joypad.buttons.items() if value) or "—"
            self.input_status.set(
                f"{self.joypad.name}: {raw or self.joypad.error or 'čekám na osy'} · tlačítka: {buttons}"
            )
            converted = controls(self.joypad.axes, self.mapping, self.joypad.buttons)
            self.mapped_status.set(
                f"{self.profile_note} · PLYN {converted['throttle'] * 100:.0f} % · BRZDA {converted['brake'] * 100:.0f} % · ŘÍZENÍ {converted['steer_deg']:.1f}°"
            )
        else:
            self.input_status.set(
                "Klávesnice: klikni do okruhu. Joypad lze zvolit v nabídce Ovládání."
            )
        if engine.driving is None:
            self.last_poll = monotonic()
            return
        if not active and engine.driving.armed:
            self.pause("Přepnuto mimo okruh. Jízda pozastavena.")
        self.last_active = active
        if active and self.source.get() == "Joypad":
            if not connected or not self.joypad.ready(self.mapping):
                if engine.driving.armed:
                    self.pause(
                        "Joypad odpojen nebo chybí mapovaná osa. Připoj jej a potvrď pokračování."
                    )
            else:
                pressed = set(self.joypad.pressed)
                if self.mapping.reset_button in pressed:
                    engine.reset()
                elif self.mapping.pause_button in pressed:
                    self.toggle_pause()
                for button, selector in (
                    (self.mapping.drive_button, "D"),
                    (self.mapping.reverse_button, "R"),
                    (self.mapping.neutral_button, "N"),
                ):
                    if button in pressed:
                        engine.vehicle_command({"selector": selector})
        if active and engine.driving.armed and not engine.snapshot()["paused"]:
            self.send_input()
        self.last_poll = monotonic()

    def refresh(self, state):
        race = state.get("driving")
        self.canvas.delete("all")
        width, height = max(600, self.canvas.winfo_width()), max(300, self.canvas.winfo_height())
        if self.view.get() == "Z čelního okna":
            self.cockpit.draw(state, width, height)
            if race:
                self.status.set(
                    race["input_fault"]
                    or ("MIMO TRAŤ · nižší přilnavost" if race["off_track"] else "Jízda z kokpitu")
                )
                self.pause_button.configure(text="Pokračovat" if state["paused"] else "Pozastavit")
            return
        points = self.track.points
        if self.follow.get() and race:
            scale = 3.0
            cx, cy = race["x_m"], race["y_m"]
        else:
            xs, ys = [p[0] for p in points], [p[1] for p in points]
            scale = min((width - 100) / (max(xs) - min(xs)), (height - 120) / (max(ys) - min(ys)))
            cx, cy = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2

        def xy(x, y):
            return width / 2 + (x - cx) * scale, height / 2 - (y - cy) * scale

        coords = [n for point in points + points[:1] for n in xy(*point)]
        self.canvas.create_line(
            *coords,
            fill="#e2e8f0",
            width=(self.track.width + 2) * scale,
            capstyle="round",
            joinstyle="round",
            tags="track:edge",
        )
        self.canvas.create_line(
            *coords,
            fill="#343b43",
            width=self.track.width * scale,
            capstyle="round",
            joinstyle="round",
            tags="track:road",
        )
        self.canvas.create_line(*coords, fill="#94a3b8", width=1, dash=(5, 10))
        x, y, heading = self.track.pose(0)
        normal = (-math.sin(heading), math.cos(heading))
        self.canvas.create_line(
            *xy(x - normal[0] * self.track.width / 2, y - normal[1] * self.track.width / 2),
            *xy(x + normal[0] * self.track.width / 2, y + normal[1] * self.track.width / 2),
            fill="white",
            width=4,
            tags="track:start",
        )
        if race:
            c, s = math.cos(race["heading_rad"]), math.sin(race["heading_rad"])
            corners = [
                n
                for a, b in ((2.2, 0.95), (2.2, -0.95), (-2.2, -0.95), (-2.2, 0.95))
                for n in xy(race["x_m"] + a * c - b * s, race["y_m"] + a * s + b * c)
            ]
            self.canvas.create_polygon(
                *corners,
                fill="#fb923c" if race["off_track"] else "#38bdf8",
                outline="white",
                width=2,
                tags="race:car",
            )
            self.canvas.create_line(
                *xy(race["x_m"], race["y_m"]),
                *xy(race["x_m"] + 8 * c, race["y_m"] + 8 * s),
                fill="#facc15",
                width=2,
            )
            vehicle = state["vehicle"]
            speed = vehicle["dashboard"]["speed_kmh"]
            rpm = vehicle["dashboard"]["rpm"]

            def number(value):
                return "—" if value is None else f"{value:.0f}"

            gear = vehicle["dashboard"]["gear"]
            gear_text = (
                "—" if gear is None else "R" if gear == -1 else "N" if gear == 0 else str(gear)
            )
            hud = (
                f"{number(speed)} km/h   {number(rpm)} ot/min   převod {gear_text}   "
                f"ABS {'●' if vehicle['abs_active'] else '○'} / ESP {'●' if vehicle['esp_active'] else '○'}"
            )
            best = "—" if race["best_lap_s"] is None else f"{race['best_lap_s']:.2f} s"
            lap = f"Kolo {race['laps'] + 1} · {race['lap_time_s']:.2f} s · nejlepší {best} · {'NEPLATNÉ (mimo trať)' if not race['lap_valid'] else 'platné'}"
            self.status.set(
                race["input_fault"]
                or ("MIMO TRAŤ · nižší přilnavost" if race["off_track"] else "Jízda po okruhu")
            )
            self.pause_button.configure(text="Pokračovat" if state["paused"] else "Pozastavit")
        else:
            hud, lap = (
                "Zapni režim jízdy tlačítkem nahoře.",
                "Společný model motoru, TCU, diferenciálu a ABS/ESP",
            )
        self.canvas.create_rectangle(0, 0, width, 58, fill="#0f172a", outline="")
        self.canvas.create_text(
            14, 17, text=hud, anchor="w", fill="#e2e8f0", font=("Sans", 13, "bold")
        )
        self.canvas.create_text(14, 42, text=lap, anchor="w", fill="#cbd5e1", font=("Sans", 11))

    def save_diagnostics(self):
        path = filedialog.asksaveasfilename(
            parent=self.parent,
            defaultextension=".json",
            initialfile="gamepad-diagnostika.json",
            filetypes=[("JSON", "*.json")],
        )
        if path:
            from pathlib import Path

            try:
                Path(path).write_text(
                    json.dumps(self.joypad.diagnostics(self.mapping), ensure_ascii=False, indent=2)
                    + "\n",
                    encoding="utf-8",
                )
            except OSError as exc:
                messagebox.showerror("Nelze uložit diagnostiku", str(exc), parent=self.parent)

    def edit_mapping(self):
        self.pause("Nastavení ovladače; po dokončení potvrď pokračování.")
        dialog = tk.Toplevel(self.parent)
        dialog.title("Mapování joypadu · JSON")
        dialog.geometry("680x670")
        ttk.Label(
            dialog,
            text="Osy a tlačítka jsou číslovány od 0. Sleduj živé osy za dialogem.\nPedály: trigger = rozsah −1…+1; positive/negative = polovina páčky.",
        ).pack(anchor="w", padx=10, pady=8)
        editor = tk.Text(dialog, width=70, height=27)
        editor.pack(fill="both", expand=True, padx=10)
        editor.insert("1.0", json.dumps(asdict(self.mapping), indent=2))

        def parse():
            data = json.loads(editor.get("1.0", "end"))
            if not isinstance(data, dict):
                raise TypeError("Mapování musí být JSON objekt")
            return Mapping(**data)

        def apply():
            try:
                self.mapping = parse()
                self.mapping_manual = True
                self.profile_error = ""
                self.profile_note = "Ruční profil"
                dialog.destroy()
            except (ValueError, TypeError) as exc:
                messagebox.showerror("Neplatné mapování", str(exc), parent=dialog)

        def load():
            path = filedialog.askopenfilename(parent=dialog, filetypes=[("JSON", "*.json")])
            if path:
                try:
                    mapping = Mapping.load(path)
                    editor.delete("1.0", "end")
                    editor.insert("1.0", json.dumps(asdict(mapping), indent=2))
                except (OSError, ValueError, TypeError) as exc:
                    messagebox.showerror("Nelze načíst", str(exc), parent=dialog)

        def save():
            try:
                mapping = parse()
                path = filedialog.asksaveasfilename(
                    parent=dialog, defaultextension=".json", initialfile="joypad.json"
                )
                if path:
                    mapping.save(path)
            except (OSError, ValueError, TypeError) as exc:
                messagebox.showerror("Nelze uložit", str(exc), parent=dialog)

        buttons = ttk.Frame(dialog, padding=10)
        buttons.pack(fill="x")
        ttk.Button(buttons, text="Načíst…", command=load).pack(side="left")
        ttk.Button(buttons, text="Uložit…", command=save).pack(side="left", padx=6)
        ttk.Button(buttons, text="Použít", command=apply).pack(side="right")

    def close(self):
        if self.check_dialog is not None:
            self.check_dialog.close()
        self.joypad.close()
