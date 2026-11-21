"""Interaktivní přehled vozu a sdílená symbolika palubní desky."""

import math
from pathlib import Path

from engine_diagram import EngineDiagram, SvgCanvas

SVG_PATH = Path(__file__).resolve().parent / "assets/vehicle-overview.svg"
PARTS = {
    "engine": (
        "Motor a ECU",
        "C++ ECU čte CKP/CMP a řídí vstřikování. Dokončené pulzy určují moment motoru.",
    ),
    "clutch": (
        "Spojka",
        "Přenáší omezený moment podle rozdílu otáček. Při řazení se rozepne a oddělí motor od kol.",
    ),
    "gearbox": (
        "Převodovka",
        "Šest dopředných stupňů, neutrál a zpátečka mění poměr otáček a momentu.",
    ),
    "differential": (
        "Přední otevřený diferenciál",
        "Dělí hnací moment stejně na přední kola. Jejich otáčky mohou být různé; zadní kola nejsou poháněná.",
    ),
    "tcu": (
        "TCU · řízení převodovky",
        "Čte otáčky, rychlost a volič z doručených CAN zpráv. Hystereze omezuje časté řazení.",
    ),
    "esp": (
        "ABS / ESP",
        "ABS snižuje tlak při brzdovém skluzu. ESP podle odchylky stáčení přibrzďuje kolo a omezuje moment.",
    ),
    "can": (
        "Virtuální CAN",
        "ECU adaptér, TCU, ABS/ESP, senzory a palubní deska sdílejí rámce s prioritami, latencí a timeoutem.",
    ),
    "dashboard": (
        "Palubní deska",
        "Přístroje čtou doručené zprávy CAN. Při timeoutu místo zastaralých údajů zobrazí pomlčky.",
    ),
    "steering": (
        "Řízení a stáčení",
        "Volant v tomto modelu zadává přímo úhel předních kol. Ze směru jízdy se odvozuje požadované stáčení.",
    ),
    "sensors": (
        "Snímače a provozní údaje",
        "Teploty, tlak oleje, napětí, palivo a orientační průtok vzduchu doplňují snímače kol a motoru.",
    ),
    "fuel": (
        "Palivová nádrž",
        "Množství paliva klesá podle odhadu spotřeby z dávek a cyklů. Nádrž zatím motor neodstavuje.",
    ),
    "body": (
        "Vůz · pohled shora",
        "Přední pohon, čtyři kola a zjednodušená dynamika. Světla, karoserie a zavěšení jsou ilustrační.",
    ),
}
for wheel in ("FL", "FR", "RL", "RR"):
    PARTS["wheel-" + wheel] = (
        f"Kolo {wheel} · "
        + {"FL": "přední levé", "FR": "přední pravé", "RL": "zadní levé", "RR": "zadní pravé"}[
            wheel
        ],
        "Vlastní rychlost kola a tlak brzdy. FL/FR jsou poháněná. Rozdíl proti rychlosti vozidla představuje prokluz; barva ukazuje brzdění nebo skluz.",
    )


def component_details(key, state, diagnostics, signals):
    title, explanation = PARTS.get(key, PARTS["body"])
    v = state.get("vehicle")
    if v is None:
        return (
            title,
            explanation,
            "Model auta je vypnutý. Zapni jej v záložce Auto / palubní deska. Schéma je nyní pouze ilustrační.",
        )
    sensors = v["sensors"]
    if key.startswith("wheel-"):
        wheel = key[6:]
        speed = sensors["wheel_speed_kmh"][wheel]
        values = f"Rychlost kola: {speed:.1f} km/h\nVůz: {v['speed_kmh']:.1f} km/h\nBrzdový tlak: {sensors['brake_pressure_bar'][wheel]:.1f} bar\nHnací moment: {v['differential']['wheel_torque_nm'][wheel]:.1f} Nm"
    else:
        values = {
            "engine": f"Motor: {state['rpm']:.0f} ot/min\nVstřik: {state['injector_ms']:.3f} ms\nPedál: {state['tps'] * 100:.1f} %",
            "clutch": f"Reakční moment: {v['engine_load_nm']:.1f} Nm\nRozepnuto při řazení: {'ano' if v['shifting'] else 'ne'}",
            "gearbox": f"Volič: {v['selector']}\nStupeň: {v['gear']}\nVstup: {sensors['gearbox_input_rpm']:.0f} ot/min\nVýstup: {sensors['gearbox_output_rpm']:.0f} ot/min",
            "differential": f"Typ: otevřený přední\nFL: {v['differential']['wheel_torque_nm']['FL']:.1f} Nm\nFR: {v['differential']['wheel_torque_nm']['FR']:.1f} Nm",
            "tcu": f"Stupeň: {v['gear']}\nŘazení: {'ano' if v['shifting'] else 'ne'}\nCAN chyba: {'ano' if v['can_fault'] else 'ne'}",
            "esp": f"ABS: {'zásah' if v['abs_active'] else 'bez zásahu'}\nESP: {'zásah' if v['esp_active'] else 'bez zásahu'}\nPovolený moment: {v['torque_factor'] * 100:.0f} %",
            "can": f"Připojena: {'ano' if v['can']['enabled'] else 'ne'}\nDoručeno: {v['can']['delivered']}\nZahozeno: {v['can']['dropped']}\nFronta: {v['can']['queue_depth']}",
            "dashboard": f"CAN data: {'nedostupná' if v['dashboard']['can_fault'] else 'platná'}\nRychlost: {v['dashboard']['speed_kmh'] if v['dashboard']['speed_kmh'] is not None else '—'} km/h",
            "steering": f"Úhel kol: {v['steer_deg']:.1f}°\nStáčení: {sensors['yaw_rate_deg_s']:.1f} °/s\nPříčné zrychlení: {sensors['lateral_accel_m_s2']:.2f} m/s²",
            "sensors": f"Kapalina: {sensors['coolant_c']:.1f} °C\nOlej: {sensors['oil_temp_c']:.1f} °C / {sensors['oil_pressure_kpa']:.0f} kPa\nSíť: {sensors['battery_v']:.1f} V",
            "fuel": f"Palivo: {sensors['fuel_level_l']:.2f} l\nLišta: {sensors['fuel_rail_pressure_kpa']:.0f} kPa",
            "body": f"Rychlost: {v['speed_kmh']:.1f} km/h\nUjeto: {v['distance_m']:.1f} m\nPovrch μ: {v['mu_left']:.2f} / {v['mu_right']:.2f}",
        }.get(key, "")
    return title, explanation, values


def wheel_color(speed, vehicle_speed, pressure):
    """Jednotná barevná legenda: šedá bez dat, červená brzda, oranžová skluz."""
    if speed is None or vehicle_speed is None or pressure is None:
        return "#94a3b8"
    if pressure > 5:
        return "#ef4444"
    slip = abs(speed - vehicle_speed) / max(abs(vehicle_speed), 3.6)
    return "#f59e0b" if slip > 0.18 else "#14b8a6"


def symbol_state(state):
    """Symbol na palubní desce čte CAN stejně jako přístroje, včetně timeoutu."""
    v = state.get("vehicle")
    result = {"wheels": {}, "steer_deg": None, "abs": None, "esp": None, "can_fault": True}
    frames = {}
    if v:
        for f in v["can"]["frames"]:
            if 0 <= v["time_us"] - f["time_us"] <= 300_000:
                frames[f["id"]] = f["signals"]
    chassis, wheels, esc = (frames.get(i) for i in (0x120, 0x110, 0x210))
    speed = chassis["speed_cms"] * 0.036 if chassis else None
    if chassis:
        result["steer_deg"] = math.degrees(chassis["steer_mrad"] / 1000)
    if esc:
        result.update(abs=bool(esc["abs"]), esp=bool(esc["esp"]))
    result["can_fault"] = not all((chassis, wheels, esc))
    for wheel in ("FL", "FR", "RL", "RR"):
        value = wheels[wheel.lower() + "_cms"] * 0.036 if wheels else None
        pressure = esc[wheel.lower()] / 255 * 100 if esc else None
        result["wheels"][wheel] = {
            "speed": value,
            "pressure": pressure,
            "color": wheel_color(value, speed, pressure),
        }
    return result


def wheel_polygon(cx, cy, angle_deg, half_width=7, half_height=17):
    """Přední kola natočená kolem vlastního středu; kladný úhel = vlevo."""
    angle = math.radians(-angle_deg)
    points = []
    for x, y in (
        (-half_width, -half_height),
        (half_width, -half_height),
        (half_width, half_height),
        (-half_width, half_height),
    ):
        points.extend(
            (
                cx + x * math.cos(angle) - y * math.sin(angle),
                cy + x * math.sin(angle) + y * math.cos(angle),
            )
        )
    return points


def draw_symbol(canvas, state, x, y, width=340, height=140):
    """Malý půdorys vozu s rychlostmi a tlaky jednotlivých kol; bez vlastního timeru."""
    data = symbol_state(state)
    sx, sy = width / 340, height / 140

    def line(points, **kwargs):
        return canvas.create_line(
            *[x + n * sx if i % 2 == 0 else y + n * sy for i, n in enumerate(points)], **kwargs
        )

    def text(px, py, content, **kwargs):
        return canvas.create_text(
            x + px * sx, y + py * sy, text=content, font=("Sans", 9), **kwargs
        )

    def polygon(points, **kwargs):
        return canvas.create_polygon(
            *[x + n * sx if i % 2 == 0 else y + n * sy for i, n in enumerate(points)], **kwargs
        )

    polygon(
        [139, 8, 201, 8, 215, 28, 215, 119, 201, 132, 139, 132, 125, 119, 125, 28],
        fill="#1e293b",
        outline="#cbd5e1",
        width=2,
        tags="symbol:body",
    )
    polygon([140, 47, 200, 47, 196, 72, 144, 72], fill="#334155", outline="#64748b")
    line([118, 35, 222, 35], fill="#38bdf8", width=3, tags="symbol:drive")
    line([118, 107, 222, 107], fill="#64748b", width=2)
    text(170, 25, "M / DIF", fill="#38bdf8")
    text(170, 88, "PŘÍĎ ↑", fill="#e2e8f0")
    for wheel, cx, cy in (("FL", 118, 35), ("FR", 222, 35), ("RL", 118, 107), ("RR", 222, 107)):
        value = data["wheels"][wheel]
        angle = (data["steer_deg"] or 0) if wheel.startswith("F") else 0
        polygon(
            wheel_polygon(cx, cy, angle),
            fill=value["color"],
            outline="#e2e8f0",
            tags="symbol:wheel-" + wheel,
        )
        tx = 52 if wheel.endswith("L") else 288
        speed = "—" if value["speed"] is None else f"{value['speed']:.1f} km/h"
        pressure = "—" if value["pressure"] is None else f"{value['pressure']:.0f} bar"
        text(tx, cy - 9, f"{wheel}  {speed}", fill="#e2e8f0", tags="symbol:label-" + wheel)
        text(tx, cy + 9, pressure, fill=value["color"])
    return data


class VehicleSvgCanvas(SvgCanvas):
    def highlight_outputs(self, state):
        v = state.get("vehicle")
        for item, key, original in self.active_items:
            color = original
            if v:
                if key.startswith("wheel-"):
                    wheel = key[6:]
                    color = wheel_color(
                        v["sensors"]["wheel_speed_kmh"][wheel],
                        v["speed_kmh"],
                        v["sensors"]["brake_pressure_bar"][wheel],
                    )
                elif key == "esp" and (v["abs_active"] or v["esp_active"]):
                    color = "#f59e0b"
                elif key == "can":
                    color = "#ef4444" if v["can_fault"] or not v["can"]["enabled"] else "#14b8a6"
                elif key == "gearbox" and v["shifting"]:
                    color = "#f59e0b"
            self.canvas.itemconfigure(item, fill=color)


class VehicleDiagram(EngineDiagram):
    SVG_PATH = SVG_PATH
    RENDERER = VehicleSvgCanvas
    DETAILS = staticmethod(component_details)
    HEADING = "Celý vůz · pohled shora · kliknutím vyber součást"
    HINT = "Podrobné schéma čte stav modelu. Malý vůz na palubní desce čte doručená CAN data a při timeoutu zešedne."
    INITIAL_PART = "body"
    SAVE_NAME = "schema-vozu.svg"
    STATUS = "Živé hodnoty modelu: tyrkysová = kolo, červená = brzdění, oranžová = skluz / zásah / řazení. Obrys vozu je ilustrační."
