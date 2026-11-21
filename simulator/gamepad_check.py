"""Pojmenované prvky gamepadu a sekvence jejich ověření; nemění jízdní profil."""

import copy
from dataclasses import dataclass

LABELS = {
    "left_x": "levá páčka vodorovně",
    "left_y": "levá páčka svisle",
    "right_x": "pravá páčka vodorovně",
    "right_y": "pravá páčka svisle",
    "dpad_x": "kříž vodorovně",
    "dpad_y": "kříž svisle",
    "face_south": "dolní A / ×",
    "face_east": "pravé B / ○",
    "face_west": "levé X / □",
    "face_north": "horní Y / △",
    "lever_left": "levá jednosměrná páka L2 / LT",
    "lever_right": "pravá jednosměrná páka R2 / RT",
    "trigger_left": "levý horní trigger L1 / LB",
    "trigger_right": "pravý horní trigger R1 / RB",
}


@dataclass
class GamepadState:
    """Abstrakce levé/pravé páčky, kříže, jednosměrných pák a tlačítek.

    Osy páček/kříže jsou −1..1, jednosměrné páky 0..1, tlačítka 0/1.
    None znamená nedostupný prvek, nikoli hodnotu nula.
    """

    values: dict
    bindings: dict

    @classmethod
    def from_joypad(cls, joypad):
        axis_map = {code: i for i, code in enumerate(joypad.axis_codes)}
        button_map = {code: i for i, code in enumerate(joypad.button_codes)}
        values = {key: None for key in LABELS}
        bindings = {}

        def axis(key, code, lever=False):
            i = axis_map.get(code)
            if i is not None:
                bindings[key] = {"type": "axis", "index": i, "code": code}
                if i in joypad.axes:
                    v = joypad.axes[i]
                    values[key] = max(0, min(1, (v + 1) / 2)) if lever else v

        def button(key, code):
            i = button_map.get(code)
            if i is not None:
                bindings[key] = {"type": "button", "index": i, "code": code}
                if i in joypad.buttons:
                    values[key] = float(joypad.buttons[i])

        axis("left_x", 0)
        axis("left_y", 1)
        if 3 in axis_map and 4 in axis_map:
            axis("right_x", 3)
            axis("right_y", 4)
            axis("lever_left", 2, True)
            axis("lever_right", 5, True)
        else:
            axis("right_x", 2)
            axis("right_y", 5)
        for key, code in (("lever_left", 10), ("lever_right", 9)):
            if key not in bindings and code in axis_map:
                axis(key, code, True)
        # Některé D-input ovladače poskytují jednosměrné páky jen digitálně.
        for key, code in (("lever_left", 0x138), ("lever_right", 0x139)):
            if key not in bindings:
                button(key, code)
        for key, code in (
            ("face_south", 0x130),
            ("face_east", 0x131),
            ("face_west", 0x134),
            ("face_north", 0x133),
            ("trigger_left", 0x136),
            ("trigger_right", 0x137),
        ):
            button(key, code)
        for key, code, negative, positive in (
            ("dpad_x", 16, 0x222, 0x223),
            ("dpad_y", 17, 0x220, 0x221),
        ):
            if code in axis_map:
                axis(key, code)
            elif negative in button_map and positive in button_map:
                n, p = button_map[negative], button_map[positive]
                bindings[key] = {"type": "buttons", "negative": n, "positive": p}
                if n in joypad.buttons and p in joypad.buttons:
                    values[key] = float(joypad.buttons[p]) - float(joypad.buttons[n])
        return cls(values, bindings)


@dataclass(frozen=True)
class CheckStep:
    key: str
    prompt: str
    target: float


def sequence():
    steps = []
    for stick, label in (("left", "LEVOU"), ("right", "PRAVOU")):
        for direction, axis, target in (
            ("vlevo", "x", -1),
            ("vpravo", "x", 1),
            ("nahoru", "y", -1),
            ("dolů", "y", 1),
        ):
            steps.append(
                CheckStep(f"{stick}_{axis}", f"Vychyl {label} páčku naplno {direction}.", target)
            )
    for direction, axis, target in (
        ("nahoru", "y", -1),
        ("dolů", "y", 1),
        ("vlevo", "x", -1),
        ("vpravo", "x", 1),
    ):
        steps.append(CheckStep("dpad_" + axis, f"Stiskni na KŘÍŽI směr {direction}.", target))
    for key in ("face_south", "face_east", "face_west", "face_north"):
        steps.append(CheckStep(key, f"Stiskni čelní tlačítko {LABELS[key]}.", 1))
    for key in ("lever_left", "lever_right", "trigger_left", "trigger_right"):
        steps.append(CheckStep(key, f"Stiskni naplno: {LABELS[key]}.", 1))
    return steps


class GamepadCheck:
    def __init__(self, state, device="", name=""):
        if not any(v is not None for v in state.values.values()):
            raise ValueError(
                "Nejsou dostupné pojmenované vstupy. Ověř připojení a metadata zařízení."
            )
        for key, v in state.values.items():
            if v is not None and abs(v) > (0.18 if key.endswith(("_x", "_y")) else 0.08):
                raise ValueError("Nejprve uvolni všechny prvky: " + LABELS[key])
        self.baseline = copy.deepcopy(state.values)
        self.bindings = copy.deepcopy(state.bindings)
        self.steps = sequence()
        self.index = 0
        self.phase = "action"
        self.results = []
        self.pending = None
        self.device, self.name = device, name
        self.message = ""
        self.neutral_since = None
        self.error = ""

    @property
    def done(self):
        return self.index >= len(self.steps)

    @property
    def prompt(self):
        if self.error:
            return self.error
        if self.done:
            return "Ověření dokončeno. Výsledky můžeš uložit."
        if self.phase in ("release", "settle"):
            return "Uvolni vstup a vrať páčky do klidu. Čekám na stabilní návrat."
        return self.steps[self.index].prompt

    def observe(self, state, now):
        if self.done or self.error:
            return
        if self.phase in ("release", "settle"):
            neutral = all(
                v is None or (state.values.get(k) is not None and abs(state.values[k] - v) <= 0.14)
                for k, v in self.baseline.items()
            )
            if neutral:
                if self.neutral_since is None:
                    self.neutral_since = now
                if now - self.neutral_since >= 0.25:
                    if self.phase == "release":
                        self.results.append(
                            {**self.pending, "status": "passed", "returned_to_rest": True}
                        )
                        self.index += 1
                    self.phase = "action"
                    self.pending = None
                    self.message = ""
                    self.neutral_since = None
            else:
                self.neutral_since = None
            return
        step = self.steps[self.index]
        value = state.values.get(step.key)
        if value is None or self.baseline.get(step.key) is None:
            self.message = "Požadovaný pojmenovaný prvek není dostupný. Můžeš jej označit jako nefunkční nebo přeskočit."
            return
        target_reached = value * step.target >= 0.75
        # U jednosměrných pák a tlačítek nechceme přijmout pouhý šum.
        if not target_reached:
            changed = [
                LABELS[k]
                for k, v in state.values.items()
                if v is not None
                and self.baseline.get(k) is not None
                and abs(v - self.baseline[k]) > 0.5
            ]
            self.message = (
                "Zachyceno: " + ", ".join(changed) + "; čekám na požadovaný prvek."
                if changed
                else "Čekám na požadovaný vstup."
            )
            return
        other_changed = [
            LABELS[k]
            for k, v in state.values.items()
            if k != step.key
            and v is not None
            and self.baseline.get(k) is not None
            and abs(v - self.baseline[k]) > 0.20
        ]
        if other_changed:
            self.message = "Použij jen požadovaný prvek; další aktivní vstupy: " + ", ".join(
                other_changed
            )
            return
        self.pending = {
            "key": step.key,
            "prompt": step.prompt,
            "target": step.target,
            "value": value,
            "rest": self.baseline[step.key],
            "binding": copy.deepcopy(state.bindings.get(step.key)),
        }
        self.phase = "release"
        self.neutral_since = None
        self.message = f"Zachyceno: {LABELS[step.key]} = {value:+.3f}. Nyní uvolni."

    def mark(self, status):
        if status not in ("failed", "skipped"):
            raise ValueError("Neplatný výsledek")
        if self.done or self.error:
            return
        step = self.steps[self.index]
        result = {
            "key": step.key,
            "prompt": step.prompt,
            "target": step.target,
            "status": status,
            "returned_to_rest": False,
        }
        if self.pending:
            result.update(
                {k: v for k, v in self.pending.items() if k not in ("key", "prompt", "target")}
            )
        self.results.append(result)
        self.index += 1
        self.phase = "settle"
        self.pending = None
        self.message = ""
        self.neutral_since = None

    def disconnected(self):
        self.error = "Ovladač odpojen. Připoj jej a zahaj nové ověření; staré výsledky lze uložit."

    def report(self):
        return copy.deepcopy(
            {
                "device": self.device,
                "name": self.name,
                "complete": self.done,
                "error": self.error,
                "rest_values": self.baseline,
                "bindings": self.bindings,
                "results": self.results,
                "pending": self.pending,
                "passed": sum(r["status"] == "passed" for r in self.results),
                "failed": sum(r["status"] == "failed" for r in self.results),
                "skipped": sum(r["status"] == "skipped" for r in self.results),
            }
        )
