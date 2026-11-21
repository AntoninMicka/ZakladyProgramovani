"""Výukové SVG přímo jako vektory Tk Canvas, bez další grafické knihovny.

Renderer podporuje základní tvary použité v přiloženém SVG. Nejde o obecný SVG editor.
Samostatný soubor přitom zůstává standardním SVG s průhledným pozadím.
"""

from pathlib import Path
import shutil
import webbrowser
from xml.etree import ElementTree as ET

SVG_PATH = Path(__file__).resolve().parent / "assets/engine-cutaway.svg"
BACKGROUND = "#f5f7fb"
SENSOR_HELP = {
    "ckp": (
        "CKP · snímač kliky",
        "Počítá průchody zubů. Z jejich rozestupu ECU odhaduje otáčky; delší mezera pomáhá najít polohu hřídele.",
    ),
    "cmp": (
        "CMP · snímač vačky",
        "Rozlišuje obě otáčky kliky v jednom čtyřtaktním cyklu. Spolu s CKP určuje, který válec je právě na řadě.",
    ),
    "map": (
        "MAP · tlak v sání",
        "Sleduje tlak v sacím potrubí. Tady jde o zjednodušenou hodnotu modelu; současný studentský algoritmus ji k řízení paliva nepoužívá.",
    ),
    "tps": (
        "TPS / výukový vstup pedálu",
        "Ve skutečnosti TPS sleduje škrticí klapku. V tomto projektu stejný kanál přenáší pedál. Samostatný snímač APP ani elektronický pohon klapky zde modelované nejsou.",
    ),
    "iat": (
        "IAT · teplota vzduchu",
        "Měří teplotu vzduchu přicházejícího do motoru. V tomto modelu má pevnou hodnotu; ECU ji zatím používá pouze jako diagnostický vstup.",
    ),
    "clt": (
        "CLT · teplota kapaliny",
        "Představuje teplotu chladicí kapaliny. Skutečná ECU může podle ní upravovat například obohacení při studeném startu; naše výuková řídicí funkce to zatím nedělá.",
    ),
    "lambda": (
        "Lambda · informace o směsi",
        "Sonda ve výfuku poskytuje informaci o směsi přes svůj řadič. Zde je lambda pouze orientační výpočet, nikoli fyzikální simulace sondy.",
    ),
}


def component_details(key, state, diagnostics, signals):
    """Popisek a živé údaje. Odděleno od Tk, aby šly ověřit významy snímačů."""
    automotive = bool(state.get("vehicle", {}).get("ecu"))
    if key == "tps" and automotive:
        return (
            "TPS / APP · klapka a pedál",
            "V režimu auta je pedál požadavek na moment; ECU ovládá zpožděnou klapku. TPS ukazuje její skutečnou polohu.",
            f"TPS: {state['tps'] * 100:.1f} %\nAPP / pedál: {state['accelerator'] * 100:.1f} %",
        )
    if key in SENSOR_HELP:
        title, explanation = SENSOR_HELP[key]
        values = {
            "ckp": f"Úroveň CKP: {state['signal_levels']['CKP']}\nKolo: {signals.teeth}−{signals.missing}\nOtáčky modelu: {state['rpm']:.0f} ot/min",
            "cmp": f"Úroveň CMP: {state['signal_levels']['CMP']}\nPolohy: {', '.join(f'{p:g}°' for p in signals.cmp_positions)}\nCyklus: {state['cycle_angle_deg']:.1f}° / 720°",
            "map": f"Tlak: {state['map_kpa']:.1f} kPa",
            "tps": f"Výukový pedál / TPS: {state['tps'] * 100:.1f} %",
            "iat": f"Teplota vzduchu: {state['iat_c']:.1f} °C",
            "clt": f"Teplota kapaliny: {state['clt_c']:.1f} °C",
            "lambda": f"Orientační lambda: {state['lambda_value']:.2f}",
        }
        return title, explanation, values[key]
    if key.startswith(("injector-", "coil-")):
        channel = int(key.split("-")[1])
        injector = key.startswith("injector")
        if channel >= state["cylinders"]:
            return (
                "Ilustrační válec " + str(channel + 1),
                "Tento válec patří pouze do přehledového obrázku čtyřválce. Aktivní model má jiný počet válců.",
                "Kanál v modelu není aktivní.",
            )
        kind = "Vstřikovač" if injector else "Cívka a svíčka"
        explanation = (
            "ECU otevře vstřikovač na vypočtenou dobu. Delší pulz v našem modelu znamená více paliva. GPIO posílá povel driveru; samotný výkonový proud není počítán."
            if injector
            else "ECU nejprve nabíjí zapalovací cívku. Po ukončení nabíjení odpovídá konec pulzu okamžiku jiskry. Vysoké napětí a energie jiskry se zde nepočítají."
        )
        durations = state["last_injection_us" if injector else "last_dwell_us"]
        width = durations.get(channel)
        # JSON může při načtení převést klíč kanálu na text.
        if width is None:
            width = durations.get(str(channel))
        active = channel in state["injector_active" if injector else "coil_charging"]
        return (
            f"{kind} · válec {channel + 1}",
            explanation,
            f"Právě aktivní: {'ano' if active else 'ne'}\nPoslední dokončený pulz: {str(width) + ' µs' if width is not None else 'zatím nezměřen'}",
        )
    if key == "ecu":
        controller = diagnostics.get("controller") or {}
        goal = controller.get("requested_rpm")
        values = f"Otáčky modelu: {state['rpm']:.0f} ot/min\nPedál: {state['tps'] * 100:.1f} %\nPoslední dávka: {state['injector_ms']:.3f} ms"
        if controller:
            values += f"\nECU naměřila: {controller['rpm']:.0f} ot/min\nPožadavek ECU: {controller['injection_us']} µs\nCíl ECU: {f'{goal:.0f} ot/min' if goal is not None else 'momentový požadavek' if controller.get('vehicle_mode') else 'studentské řízení'}"
        else:
            values += "\nVlastní měření a cíl ECU nejsou\nv tomto snímku dostupné."
        return (
            "ECU · řídicí jednotka",
            "Čte snímače a rozhoduje o výstupech. V režimu auta používá update_vehicle_control() pro klapku, směs a ochrany; v samostatném motoru zůstává studentská update_control().",
            values,
        )
    if key == "pedal":
        return (
            "Pedál · vstup řidiče",
            "Poloha pedálu vstupuje do ECU. V režimu auta jde o požadavek na moment, u samostatného motoru význam určuje studentská funkce. Python moment znovu pedálem nenásobí.",
            f"Poloha pedálu: {state['accelerator'] * 100:.1f} %",
        )
    if key == "load":
        return (
            "Mechanická zátěž",
            "Brzdný moment představuje práci, kterou musí motor vykonávat. Při stejném cíli otáček bude budoucí regulátor muset větší zátěž vyrovnat větší dávkou paliva.",
            f"Zátěž: {state['load_nm']:.1f} Nm",
        )
    if key == "intake":
        return (
            "Sání · cesta vzduchu",
            "Vzduch prochází filtrem a sacím potrubím do válců. Obrázek ukazuje místo MAP, IAT a TPS. Samostatná fyzika průtoku vzduchu ani pohon klapky zde nejsou modelované.",
            f"MAP: {state['map_kpa']:.1f} kPa\nIAT: {state['iat_c']:.1f} °C",
        )
    if key == "exhaust":
        return (
            "Výfuk · cesta spalin",
            "Po pracovním zdvihu odcházejí spaliny výfukovým ventilem. Sonda lambda je zakreslená ve výfuku, její hodnota je v simulátoru jen orientační.",
            f"Lambda: {state['lambda_value']:.2f}",
        )
    return (
        "Motor · průhledový řez",
        "Řez ilustračním řadovým čtyřválcem odhaluje ventily, písty, ojnice a klikový hřídel. Samotné SVG je statické; polohy pístů nejsou časovou animací. Živou animaci najdeš v záložce Motor.",
        f"Aktivní model: {state['cylinders']} válců\nOtáčky: {state['rpm']:.0f} ot/min\nČas modelu: {state['simulation_time_us'] / 1e6:.3f} s",
    )


class SvgCanvas:
    """Malá vektorová vykreslovací vrstva pro přiložené tvary SVG."""

    SUPPORTED = {
        "svg",
        "g",
        "title",
        "desc",
        "rect",
        "circle",
        "ellipse",
        "line",
        "polyline",
        "polygon",
        "text",
    }

    def __init__(self, canvas, path=SVG_PATH):
        self.canvas = canvas
        self.root = ET.parse(path).getroot()
        _, _, self.width, self.height = map(float, self.root.attrib["viewBox"].split())
        self.active_items = []

    def color(self, value, opacity="1"):
        if value == "none":
            return ""
        opacity = float(opacity)
        if opacity >= 1:
            return value
        rgb = self.canvas.winfo_rgb(value)
        bg = self.canvas.winfo_rgb(BACKGROUND)
        return "#" + "".join(
            f"{round((a * opacity + b * (1 - opacity)) / 257):02x}" for a, b in zip(rgb, bg)
        )

    def draw(self, scale):
        self.canvas.delete("all")
        self.active_items.clear()

        def walk(node, inherited):
            tag = node.tag.rsplit("}", 1)[-1]
            if tag not in self.SUPPORTED:
                raise ValueError("Nepodporovaný prvek ve výukovém SVG: " + tag)
            attrs = {**inherited, **node.attrib}
            if tag in ("svg", "g"):
                for child in node:
                    walk(child, attrs)
                return
            if tag in ("title", "desc"):
                return

            def value(name, default=0):
                return float(attrs.get(name, default)) * scale

            fill = self.color(attrs.get("fill", "none"), attrs.get("fill-opacity", "1"))
            stroke = self.color(attrs.get("stroke", "none"), attrs.get("stroke-opacity", "1"))
            key = attrs.get("data-part")
            tags = ("shape", "part:" + key) if key else ("shape",)
            options = dict(
                fill=fill, outline=stroke, width=max(0.7, value("stroke-width", 1)), tags=tags
            )
            if tag == "rect":
                item = self.canvas.create_rectangle(
                    value("x"),
                    value("y"),
                    value("x") + value("width"),
                    value("y") + value("height"),
                    **options,
                )
            elif tag in ("circle", "ellipse"):
                rx = value("r") if tag == "circle" else value("rx")
                ry = value("r") if tag == "circle" else value("ry")
                item = self.canvas.create_oval(
                    value("cx") - rx,
                    value("cy") - ry,
                    value("cx") + rx,
                    value("cy") + ry,
                    **options,
                )
            elif tag in ("line", "polyline", "polygon"):
                points = (
                    [value("x1"), value("y1"), value("x2"), value("y2")]
                    if tag == "line"
                    else [float(n) * scale for n in attrs["points"].replace(",", " ").split()]
                )
                if tag == "polygon":
                    item = self.canvas.create_polygon(points, **options)
                else:
                    options.pop("outline")
                    options["fill"] = stroke
                    if attrs.get("stroke-dasharray"):
                        options["dash"] = tuple(
                            max(1, round(float(n) * scale))
                            for n in attrs["stroke-dasharray"].split()
                        )
                    item = self.canvas.create_line(points, **options)
            else:
                # SVG používá pixely a souřadnici účaří. Tk kladnou velikost chápe
                # jako body; záporná velikost zachová pixely i při jiném DPI displeje.
                font = (
                    "Sans",
                    -max(8, round(value("font-size", 16))),
                    "bold" if attrs.get("font-weight") == "bold" else "normal",
                )
                descent = int(self.canvas.tk.call("font", "metrics", font, "-descent"))
                item = self.canvas.create_text(
                    value("x"),
                    value("y") + descent,
                    text=node.text or "",
                    fill=fill,
                    font=font,
                    anchor={"start": "sw", "middle": "s", "end": "se"}.get(
                        attrs.get("text-anchor", "start"), "sw"
                    ),
                    tags=tags,
                )
            if attrs.get("data-active"):
                self.active_items.append((item, key, fill))

        walk(self.root, {})
        self.canvas.configure(scrollregion=(0, 0, self.width * scale, self.height * scale))

    def highlight_outputs(self, state):
        for item, key, original in self.active_items:
            injector = key.startswith("injector-")
            channel = int(key.split("-")[1])
            active = channel in state["injector_active" if injector else "coil_charging"]
            self.canvas.itemconfigure(item, fill="#fb923c" if active else original)


class EngineDiagram:
    SVG_PATH = SVG_PATH
    RENDERER = SvgCanvas
    DETAILS = staticmethod(component_details)
    HEADING = "Průhledový řez · kliknutím vyber díl"
    HINT = (
        "Krátké pulzy mohou proběhnout mezi dvěma obnoveními obrazovky. Schéma neměří piny Wokwi."
    )
    INITIAL_PART = "ecu"
    SAVE_NAME = "schema-motoru.svg"
    STATUS = "Samostatné SVG má průhledné pozadí. Řez je ilustrační čtyřválec; hodnoty patří aktivnímu modelu."

    def __init__(self, page, app):
        import tkinter as tk
        from tkinter import ttk

        self.app = app
        self.page = page
        self.selected = self.INITIAL_PART
        self.state = app.engine.snapshot()
        self.diagnostics = {}
        toolbar = ttk.Frame(page)
        toolbar.pack(fill="x", pady=(0, 8))
        ttk.Label(toolbar, text=self.HEADING).pack(side="left")
        self.zoom = tk.StringVar(value="Přizpůsobit")
        zoom = ttk.Combobox(
            toolbar,
            textvariable=self.zoom,
            width=14,
            state="readonly",
            values=("Přizpůsobit", "50 %", "75 %", "100 %", "125 %", "150 %", "200 %"),
        )
        zoom.pack(side="left", padx=12)
        zoom.bind("<<ComboboxSelected>>", lambda event: self.redraw())
        ttk.Button(toolbar, text="Uložit SVG…", command=self.save_svg).pack(side="right")
        ttk.Button(
            toolbar, text="Otevřít SVG", command=lambda: webbrowser.open(self.SVG_PATH.as_uri())
        ).pack(side="right", padx=8)
        split = ttk.Panedwindow(page, orient="horizontal")
        split.pack(fill="both", expand=True)
        drawing = ttk.Frame(split)
        side = ttk.Frame(split, padding=(14, 8))
        split.add(drawing, weight=4)
        split.add(side, weight=1)
        self.canvas = tk.Canvas(
            drawing, background=BACKGROUND, highlightthickness=0, width=650, height=400
        )
        vertical = ttk.Scrollbar(drawing, orient="vertical", command=self.canvas.yview)
        horizontal = ttk.Scrollbar(drawing, orient="horizontal", command=self.canvas.xview)
        self.canvas.configure(xscrollcommand=horizontal.set, yscrollcommand=vertical.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        drawing.rowconfigure(0, weight=1)
        drawing.columnconfigure(0, weight=1)
        self.renderer = self.RENDERER(self.canvas, self.SVG_PATH)
        self.canvas.bind("<Configure>", lambda event: self.redraw())
        self.canvas.bind("<Button-1>", self.clicked)
        self.title = tk.StringVar()
        self.explanation = tk.StringVar()
        self.values = tk.StringVar()
        ttk.Label(side, textvariable=self.title, font=("Sans", 14, "bold"), wraplength=260).pack(
            anchor="w", pady=(0, 12)
        )
        ttk.Label(side, textvariable=self.explanation, wraplength=260, justify="left").pack(
            anchor="w"
        )
        ttk.Separator(side).pack(fill="x", pady=16)
        ttk.Label(side, text="ŽIVÉ HODNOTY", font=("Sans", 10, "bold")).pack(
            anchor="w", pady=(0, 8)
        )
        ttk.Label(side, textvariable=self.values, wraplength=260, justify="left").pack(anchor="w")
        ttk.Label(
            side,
            text=self.HINT,
            wraplength=260,
            foreground="#94a3b8",
        ).pack(anchor="w", pady=20)
        self.status = tk.StringVar(value=self.STATUS)
        ttk.Label(page, textvariable=self.status, wraplength=1060).pack(anchor="w", pady=(8, 0))
        self.show_details()

    def redraw(self):
        width, height = self.canvas.winfo_width(), self.canvas.winfo_height()
        if width < 10 or height < 10:
            return
        scale = (
            min(width / self.renderer.width, height / self.renderer.height)
            if self.zoom.get() == "Přizpůsobit"
            else float(self.zoom.get().split()[0]) / 100
        )
        self.renderer.draw(scale)
        self.renderer.highlight_outputs(self.state)
        self.mark_selection()

    def mark_selection(self):
        self.canvas.delete("selection")
        bounds = self.canvas.bbox("part:" + self.selected)
        if bounds:
            x1, y1, x2, y2 = bounds
            self.canvas.create_rectangle(
                x1 - 4,
                y1 - 4,
                x2 + 4,
                y2 + 4,
                outline="#7c3aed",
                width=2,
                dash=(4, 3),
                tags="selection",
            )

    def clicked(self, event):
        x, y = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
        for item in reversed(self.canvas.find_overlapping(x - 2, y - 2, x + 2, y + 2)):
            for tag in self.canvas.gettags(item):
                if tag.startswith("part:"):
                    self.select(tag[5:])
                    return

    def select(self, key):
        self.selected = key
        self.mark_selection()
        self.show_details()

    def show_details(self):
        title, explanation, values = self.DETAILS(
            self.selected, self.state, self.diagnostics, self.app.engine.signals
        )
        self.title.set(title)
        self.explanation.set(explanation)
        self.values.set(values)

    def refresh(self, state, diagnostics):
        self.state, self.diagnostics = state, diagnostics
        self.renderer.highlight_outputs(state)
        self.show_details()

    def save_svg(self):
        from tkinter import filedialog

        selected = filedialog.asksaveasfilename(
            parent=self.page.winfo_toplevel(),
            title="Uložit průhledné SVG schéma",
            defaultextension=".svg",
            initialfile=self.SAVE_NAME,
            filetypes=(("SVG", "*.svg"),),
        )
        if selected:
            try:
                shutil.copyfile(self.SVG_PATH, selected)
                self.status.set("Uloženo statické SVG s průhledným pozadím: " + selected)
            except OSError as exc:
                self.status.set("SVG se nepodařilo uložit: " + str(exc))
