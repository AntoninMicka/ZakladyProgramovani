"""Čitelné školní schéma: motor/kabeláž → vstupy ECU → MCU → drivery/zátěže."""

from html import escape


def diagram(engine, profile, target):
    p, e = profile, engine
    parts, wires, pinmap = [], [], []

    def part(kind, name, x, y, **attrs):
        parts.append(dict(type=kind, id=name, left=x, top=y, attrs=attrs))

    def text(name, x, y, label):
        part("wokwi-text", name, x, y, text=label)

    def wire(a, b, color, path=None):
        wires.append([a, b, color, path or []])

    def gpio(number):
        return p.get("digital_labels", {}).get(str(number), f"{p['digital_prefix']}{number}")

    part("chip-engine-interface", "engine", -1000, 0)
    part("chip-sensor-front-end", "inputs", -500, 0)
    part(p["part"], "ecu", 0, 0)
    part("chip-output-stage", "drivers", 550, 0)
    part("wokwi-logic-analyzer", "logic", 0, -450)
    part("wokwi-slide-switch", "main_relay", 550, -180, bounce="0")
    text("title", -1000, -600, f"ECU / {e['cylinders']} valcu, ctyrtakt - signalove schema")
    text(
        "power_note",
        -1000,
        -550,
        "V aute: baterie 12 V -> pojistka -> hlavni rele -> zateze / regulator ECU\n"
        "Zde: cervena sit = logicke napajeni MCU; POWER_EN = model napajeni zatezi, nikoli 12 V.",
    )
    text(
        "motor_label",
        -1100,
        -120,
        f"MOTOR / MODEL\nCKP {e['ckp']['teeth']}-{e['ckp']['missing']}, CMP, MAP, TPS, IAT, CLT, lambda\nUART do Pythonu patri simulatoru, ne ECU",
    )
    text(
        "inputs_label",
        -500,
        -100,
        "KABELAZ / VSTUPY ECU\nCKP/CMP uz po tvarovani\nanalogove signaly uz v rozsahu ADC",
    )
    text(
        "ecu_label",
        0,
        -100,
        "ECU - mikroprocesor\nCKP/CMP -> casovani -> INJ/IGN\nUART TX = pouze diagnostika",
    )
    text(
        "driver_label",
        550,
        -100,
        "VYKONOVE VYSTUPY\nINJ: low-side MOSFET + ochrana\nIGN: IGBT / chytra civka + omezeni napeti\nZde logicky model driveru a zateze",
    )
    text(
        "switch_label",
        670,
        -180,
        "HLAVNI RELE: vlevo ON / vpravo OFF\nOdpoji zateze, ECU a snimace bezi dal",
    )
    text(
        "loads_label",
        1150,
        -100,
        "INDIKACE ZATEZI\nzelena = vstrik otevren\nzluta = civka se nabiji; zhasnuti = konec nabijeni",
    )
    power, ground = f"ecu:{p['power']}", f"ecu:{p['ground']}"
    for supply, earth in (
        ("engine:VCC", "engine:GND"),
        ("inputs:VCC", "inputs:GND"),
        ("drivers:VCC", "drivers:PGND"),
    ):
        wire(power, supply, "red")
        wire(ground, earth, "black")
    wire(ground, "logic:GND", "black")
    wire(ground, "main_relay:3", "black")
    wire(power, "main_relay:1", "red")
    wire("main_relay:2", "drivers:POWER_EN", "red")
    wire("$serialMonitor:TX", "engine:RX", "gray")
    wire("engine:TX", "$serialMonitor:RX", "gray")
    wire(f"ecu:{p['diagnostic_tx']}", "engine:DIAG_RX", "gray")
    sensors = ("CKP", "CMP", "MAP", "TPS", "IAT", "CLT", "LAMBDA")
    labels = [gpio(p["ckp"]), gpio(p["cmp"]), *p["analog_labels"]]
    for i, (name, pin) in enumerate(zip(sensors, labels)):
        color = ("blue", "purple")[i] if i < 2 else "orange"
        wire(f"engine:{name}", f"inputs:{name}_IN", color)
        wire(f"inputs:{name}_OUT", f"ecu:{pin}", color)
        pinmap.append((name, pin))
    for kind, pins, color, active in (
        ("INJ", p["injectors"], "green", e["capture"]["injector_active_high"]),
        ("IGN", p["ignition"], "yellow", e["capture"]["ignition_active_high"]),
    ):
        for i in range(4):
            name, y = f"{kind}{i + 1}", i * 125 + (0 if kind == "INJ" else 520)
            pinmap.append((name, gpio(pins[i])))
            wire(f"ecu:{gpio(pins[i])}", f"drivers:{name}_CTRL", color)
            wire(f"drivers:{name}_LOAD", f"engine:{name}", color)
            part("wokwi-led", name.lower(), 1200, y, color=color, label=name, fps="80")
            part("wokwi-resistor", "r_" + name.lower(), 1100, y + 30, value="1000")
            if active:
                wire(f"drivers:{name}_LOAD", "r_" + name.lower() + ":1", color)
                wire("r_" + name.lower() + ":2", name.lower() + ":A", color)
                wire(name.lower() + ":C", ground, "black")
            else:
                wire(power, "r_" + name.lower() + ":1", "red")
                wire("r_" + name.lower() + ":2", name.lower() + ":A", color)
                wire(name.lower() + ":C", f"drivers:{name}_LOAD", color)
    for channel, point in enumerate(
        (
            "inputs:CKP_OUT",
            "inputs:CMP_OUT",
            "drivers:INJ1_LOAD",
            "drivers:IGN1_LOAD",
            "ecu:" + gpio(p["injectors"][0]),
            "ecu:" + gpio(p["ignition"][0]),
            "drivers:POWER_EN",
        )
    ):
        wire(point, f"logic:D{channel}", "blue")
    text(
        "logic_label",
        230,
        -450,
        "LOGIC ANALYZER\nD0 CKP / D1 CMP / D2 INJ1 zatez / D3 IGN1 zatez\nD4 INJ1 povel / D5 IGN1 povel / D6 napajeni zatezi\nLED zprumeruje kratke pulzy; sirky merime ve VCD.",
    )
    text(
        "grounds_label",
        -500,
        850,
        "GND snimacu (SGND) a vykonova zem (PGND) maji v tomto modelu spolecny bod u ECU.\n"
        "Model nepocita proudy, otepleni, ruseni, zpetne napeti ani skutecnou jiskru.",
    )
    return dict(
        version=1,
        author="ECU Hardware Simulator",
        editor="wokwi",
        parts=parts,
        connections=wires,
        serialMonitor=dict(display="always", newline="lf"),
    ), pinmap


def drawing(target, engine):
    """Samostatný přehledový SVG s částmi, které elektrický Wokwi model zjednodušuje."""
    svg = [
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1400 1000" role="img" aria-labelledby="title desc">',
        '<title id="title">ECU - snímače, vstupy, procesor a výkonové výstupy</title>',
        '<desc id="desc">Blokové schéma automobilové ECU se snímači, MOSFET a IGBT drivery. Wokwi simuluje logické povely a aktivitu, nikoli vysoké proudy či jiskru.</desc>',
        '<rect width="1400" height="1000" fill="#0f172a"/>',
        '<g font-family="DejaVu Sans,Arial,sans-serif" fill="#e2e8f0">',
    ]

    def text(x, y, value, size=16, color="#e2e8f0"):
        svg.append(
            f'<text x="{x}" y="{y}" font-size="{size}" fill="{color}">{escape(value)}</text>'
        )

    def box(x, y, w, h, title, color="#64748b"):
        svg.append(
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="10" fill="#1e293b" stroke="{color}" stroke-width="2"/>'
        )
        text(x + 15, y + 28, title, 18, color)

    def line(x1, y1, x2, y2, color="#38bdf8"):
        svg.append(
            f'<path d="M{x1} {y1} L{x2} {y2}" stroke="{color}" stroke-width="3" fill="none"/>'
        )

    text(35, 42, "ECU / čtyřtaktní motor · " + target, 26)
    box(35, 70, 245, 95, "Baterie auta · 12 V", "#f87171")
    text(50, 125, "Pojistka + ochrana napájení")
    line(280, 115, 350, 115, "#f87171")
    box(350, 70, 280, 95, "Hlavní relé / svorka 15", "#f87171")
    text(365, 125, "Ve Wokwi přepínač POWER_EN")
    line(630, 115, 730, 115, "#f87171")
    box(730, 70, 270, 95, "Napájení zátěží · 12 V", "#f87171")
    box(1050, 70, 315, 95, "Regulátory ECU", "#f87171")
    text(
        1065,
        125,
        "5 V snímače / " + ("3,3 V MCU (ESP32)" if target == "esp32" else "5 V MCU (Mega)"),
    )
    line(1000, 115, 1050, 115, "#f87171")
    box(35, 215, 340, 440, "MOTOR / SNÍMAČE", "#38bdf8")
    box(425, 215, 330, 440, "ECU: vstupy + procesor", "#a78bfa")
    box(825, 215, 540, 440, "ECU: drivery → skutečné zátěže", "#4ade80")
    for i, label in enumerate(
        (
            f"CKP · poloha kliky · {engine['ckp']['teeth']}-{engine['ckp']['missing']}",
            "CMP · poloha vačky · cyklus 720°",
            "MAP · tlak v sání",
            "TPS · výukový vstup pedálu",
            "IAT / CLT · teplotní snímače",
            "Lambda · výstup jejího řadiče",
        )
    ):
        y = 285 + i * 53
        text(50, y, label)
        line(375, y - 5, 425, y - 5)
    text(440, 285, "CKP/CMP: vstup po tvarování")
    text(440, 338, "Analog: přizpůsobení rozsahu ADC")
    text(440, 391, "MCU čte polohu a počítá termíny")
    text(440, 444, "GPIO vysílá řídicí povely")
    text(440, 497, "MCU nenapájí cívky ani vstřiky")
    text(440, 550, "SGND: zem snímačů")
    for i in range(4):
        y = 280 + i * 83
        line(755, y, 840, y, "#4ade80")
        text(850, y + 5, f"INJ{i + 1}: MOSFET → vstřikovač → +12 V", 16, "#4ade80")
        text(850, y + 32, f"IGN{i + 1}: IGBT / chytrá cívka → svíčka", 16, "#facc15")
    text(840, 620, "PGND · omezení indukčních špiček · logická indikace LED", 14)
    box(35, 695, 650, 115, "SIMULAČNÍ ROZHRANÍ", "#38bdf8")
    text(50, 748, "Python ↔ RFC2217 / UART ↔ Engine Interface Custom Chip")
    text(50, 779, "Budí snímače; měří aktivitu zátěží až ZA modelem driverů.")
    box(730, 695, 635, 115, "LOGIC ANALYZER / VCD", "#a78bfa")
    text(745, 748, "D0 CKP · D1 CMP · D2 INJ1 LOAD · D3 IGN1 LOAD")
    text(745, 779, "D4 INJ1 CTRL · D5 IGN1 CTRL · D6 POWER_EN")
    text(
        35,
        860,
        "Červený horní řetězec popisuje skutečnou funkci auta; Wokwi používá logické napájecí úrovně.",
        16,
        "#fbbf24",
    )
    text(
        35,
        895,
        "Vstupní blok už dostává signály v rozsahu MCU. Nepočítá analogovou elektroniku VR / NTC / lambda.",
    )
    text(
        35,
        930,
        "Výstupní blok počítá povel AND POWER_EN. Nepočítá proud, magnetické pole, přepětí ani vysoké napětí svíčky.",
    )
    svg.append("</g></svg>")
    return "\n".join(svg) + "\n"
