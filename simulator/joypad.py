"""Neblokující Linux joydev vstup bez další závislosti; čtení pouze z /dev/input/js*.

Formát události podle docs.kernel.org/input/joydev/joystick-api.html.
Mapování a přepočet jsou oddělené od zařízení a lze je testovat bez ovladače.
"""

import json
import math
import os
import struct
from dataclasses import asdict, dataclass, replace
from pathlib import Path

EVENT = struct.Struct("=IhBB")


@dataclass(frozen=True)
class Mapping:
    steer_axis: int = 0
    throttle_axis: int = 5
    brake_axis: int = 2
    throttle_button: int | None = None
    brake_button: int | None = None
    pedal_deadzone: float = 0.04
    steer_invert: bool = False
    throttle_invert: bool = False
    brake_invert: bool = False
    throttle_mode: str = "trigger"
    brake_mode: str = "trigger"
    deadzone: float = 0.08
    sensitivity: float = 1.6
    pause_button: int = 7
    reset_button: int = 0
    drive_button: int = 5
    reverse_button: int = 4
    neutral_button: int = 2

    def __post_init__(self):
        for key, value in asdict(self).items():
            if key.endswith(("_axis", "_button")):
                if key in ("throttle_button", "brake_button") and value is None:
                    continue
                if type(value) is not int or not 0 <= value <= 255:
                    raise ValueError("Mapování: neplatné číslo osy/tlačítka")
            elif key.endswith("_invert") and type(value) is not bool:
                raise ValueError("Mapování: invert musí být true/false")
        if self.throttle_mode not in ("trigger", "positive", "negative") or self.brake_mode not in (
            "trigger",
            "positive",
            "negative",
        ):
            raise ValueError("Režim pedálu: trigger, positive nebo negative")
        if (
            type(self.pedal_deadzone) not in (int, float)
            or not math.isfinite(self.pedal_deadzone)
            or not 0 <= self.pedal_deadzone < 0.5
        ):
            raise ValueError("Mrtvá zóna pedálů musí být 0 až méně než 0,5")
        if not math.isfinite(self.deadzone) or not 0 <= self.deadzone < 0.5:
            raise ValueError("Mrtvá zóna musí být 0 až méně než 0,5")
        if not math.isfinite(self.sensitivity) or not 0.5 <= self.sensitivity <= 3:
            raise ValueError("Citlivost musí být 0,5 až 3")
        if (
            len(
                {
                    self.pause_button,
                    self.reset_button,
                    self.drive_button,
                    self.reverse_button,
                    self.neutral_button,
                }
            )
            != 5
        ):
            raise ValueError("Akce potřebují různá tlačítka")

    @classmethod
    def load(cls, path):
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise TypeError("Mapování musí být JSON objekt")
        return cls(**data)

    def save(self, path):
        Path(path).write_text(
            json.dumps(asdict(self), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )


def deadzone(value, width):
    if abs(value) <= width:
        return 0.0
    return math.copysign(min(1, (abs(value) - width) / (1 - width)), value)


def controls(axes, mapping, buttons=None):
    buttons = buttons or {}

    def pedal(axis, mode, invert, button):
        if button is not None:
            return float(bool(buttons.get(button, False)))
        # Nenahlášená osa nikdy nesmí znamenat půl plynu.
        if axis not in axes:
            return 0.0
        value = -axes[axis] if invert else axes[axis]
        if mode == "trigger":
            value = max(0, min(1, (value + 1) / 2))
            return max(0, (value - mapping.pedal_deadzone) / (1 - mapping.pedal_deadzone))
        return max(0, deadzone(value if mode == "positive" else -value, mapping.deadzone))

    steer = deadzone(axes.get(mapping.steer_axis, 0), mapping.deadzone)
    steer = math.copysign(abs(steer) ** mapping.sensitivity, steer)
    if mapping.steer_invert:
        steer = -steer
    return {
        "throttle": pedal(
            mapping.throttle_axis,
            mapping.throttle_mode,
            mapping.throttle_invert,
            mapping.throttle_button,
        ),
        "brake": pedal(
            mapping.brake_axis, mapping.brake_mode, mapping.brake_invert, mapping.brake_button
        ),
        "steer_deg": -steer * 30,
    }


# Linux input-event-codes.h: významy os a tlačítek, nikoli jejich joydev pořadí.
AXIS_NAMES = {
    0: "ABS_X",
    1: "ABS_Y",
    2: "ABS_Z",
    3: "ABS_RX",
    4: "ABS_RY",
    5: "ABS_RZ",
    6: "ABS_THROTTLE",
    7: "ABS_RUDDER",
    9: "ABS_GAS",
    10: "ABS_BRAKE",
    16: "ABS_HAT0X",
    17: "ABS_HAT0Y",
}


def detect_mapping(axis_codes, button_codes):
    """Stejný princip jako Workspace EvdevGamepad: významy ABS/BTN z driveru.

    Z/RZ jsou triggery jen při samostatném RX/RY pravém sticku. Pokud chybí,
    mohou samy tvořit pravý stick a jejich použití jako pedálů by dalo půl plynu.
    """
    axes = {code: i for i, code in enumerate(axis_codes)}
    buttons = {code: i for i, code in enumerate(button_codes)}
    if 0 not in axes:
        return None, "Nerozpoznána osa ABS_X; použij ruční mapování."
    actions = {
        "pause_button": 0x13B,
        "reset_button": 0x130,
        "drive_button": 0x137,
        "reverse_button": 0x136,
        "neutral_button": 0x131,
    }
    if any(code not in buttons for code in actions.values()):
        return None, "Chybí standardní BTN tlačítka; použij ruční mapování."
    mapping = Mapping(steer_axis=axes[0], **{key: buttons[code] for key, code in actions.items()})
    if 9 in axes and 10 in axes:
        return replace(
            mapping, throttle_axis=axes[9], brake_axis=axes[10]
        ), "Pedály ABS_GAS / ABS_BRAKE"
    if all(code in axes for code in (2, 3, 4, 5)):
        return replace(
            mapping, throttle_axis=axes[5], brake_axis=axes[2]
        ), "Triggery ABS_RZ / ABS_Z (Xbox / DualShock layout)"
    if 0x138 in buttons and 0x139 in buttons:
        return replace(
            mapping, throttle_button=buttons[0x139], brake_button=buttons[0x138]
        ), "Digitální R2/L2 (BTN_TR2 / BTN_TL2)"
    if 1 in axes:
        return replace(
            mapping,
            throttle_axis=axes[1],
            brake_axis=axes[1],
            throttle_mode="negative",
            brake_mode="positive",
        ), "Páčka ABS_Y: nahoru plyn, dolů brzda; triggery nerozpoznány"
    return None, "Pedály nerozpoznány; použij ruční mapování."


class Joypad:
    def __init__(self, device="/dev/input/js0"):
        self.device = str(device)
        self.fd = None
        self.axes = {}
        self.buttons = {}
        self.pressed = set()
        self.buffer = bytearray()
        self.error = "Ovladač nepřipojen"
        self.name = Path(device).name
        self.axis_codes = []
        self.button_codes = []
        self.detected_mapping = None
        self.layout = "Metadata zařízení nejsou dostupná"

    @staticmethod
    def devices():
        return sorted(str(p) for p in Path("/dev/input").glob("js*"))

    def open(self):
        self.close()
        try:
            self.fd = os.open(self.device, os.O_RDONLY | os.O_NONBLOCK)
            name = Path("/sys/class/input") / Path(self.device).name / "device/name"
            self.name = name.read_text().strip() if name.is_file() else Path(self.device).name
            self.error = ""
            self.read_layout()
        except OSError as exc:
            self.close()
            self.error = f"{self.device}: {exc.strerror}"
        return self.fd is not None

    def read_layout(self):
        # Hodnoty ioctl ověřené proti místnímu linux/joystick.h (Linux asm-generic).
        import fcntl

        try:
            axes, buttons = bytearray(1), bytearray(1)
            axis_map, button_map, name = bytearray(64), bytearray(1024), bytearray(128)
            fcntl.ioctl(self.fd, 0x80016A11, axes, True)  # JSIOCGAXES
            fcntl.ioctl(self.fd, 0x80016A12, buttons, True)  # JSIOCGBUTTONS
            fcntl.ioctl(self.fd, 0x80406A32, axis_map, True)  # JSIOCGAXMAP
            fcntl.ioctl(self.fd, 0x84006A34, button_map, True)  # JSIOCGBTNMAP
            self.axis_codes = list(axis_map[: axes[0]])
            self.button_codes = list(struct.unpack("=512H", button_map)[: buttons[0]])
            try:
                fcntl.ioctl(self.fd, 0x80806A13, name, True)  # JSIOCGNAME(128)
                self.name = bytes(name).split(b"\0", 1)[0].decode("utf-8", errors="replace")
            except OSError:
                pass
            self.detected_mapping, self.layout = detect_mapping(self.axis_codes, self.button_codes)
        except OSError as exc:
            self.layout = f"Nelze načíst rozložení: {exc.strerror}; použij ruční mapování."

    def semantic_state(self):
        from gamepad_check import GamepadState

        return GamepadState.from_joypad(self)

    def diagnostics(self, mapping):
        return {
            "device": self.device,
            "name": self.name,
            "connected": self.fd is not None,
            "layout": self.layout,
            "error": self.error,
            "axis_codes": self.axis_codes,
            "button_codes": self.button_codes,
            "axis_names": [AXIS_NAMES.get(code, f"ABS_{code}") for code in self.axis_codes],
            "axes": dict(self.axes),
            "buttons": dict(self.buttons),
            "mapping": asdict(mapping),
            "controls": controls(self.axes, mapping, self.buttons),
            "ready": self.ready(mapping),
        }

    def neutral(self, mapping):
        values = controls(self.axes, mapping, self.buttons)
        return (
            self.ready(mapping)
            and values["throttle"] <= 0.05
            and values["brake"] <= 0.05
            and abs(values["steer_deg"]) <= 3
        )

    def feed(self, data):
        self.buffer.extend(data)
        while len(self.buffer) >= EVENT.size:
            _, value, kind, number = EVENT.unpack(self.buffer[: EVENT.size])
            del self.buffer[: EVENT.size]
            initial = bool(kind & 0x80)
            kind &= ~0x80
            if kind == 2:
                self.axes[number] = max(-1, min(1, value / 32767))
            elif kind == 1:
                if value and not self.buttons.get(number, False) and not initial:
                    self.pressed.add(number)
                self.buttons[number] = bool(value)

    def poll(self):
        self.pressed.clear()
        if self.fd is None:
            return False
        try:
            # Horní mez chrání GUI před zařízením zaplavujícím vstup.
            for _ in range(32):
                try:
                    data = os.read(self.fd, EVENT.size * 64)
                except BlockingIOError:
                    return True
                if not data:
                    raise OSError("Ovladač odpojen")
                self.feed(data)
            return True
        except OSError as exc:
            self.close()
            self.error = str(exc)
            return False

    def ready(self, mapping):
        if self.fd is None or mapping.steer_axis not in self.axes:
            return False
        for axis, button in (
            (mapping.throttle_axis, mapping.throttle_button),
            (mapping.brake_axis, mapping.brake_button),
        ):
            if button is not None:
                if button not in self.buttons:
                    return False
            elif axis not in self.axes:
                return False
        return True

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
        self.fd = None
        self.axes.clear()
        self.buttons.clear()
        self.pressed.clear()
        self.buffer.clear()
        self.axis_codes.clear()
        self.button_codes.clear()
        self.detected_mapping = None
        self.layout = "Metadata zařízení nejsou dostupná"
