"""První podélný model auta s jednoduchou dynamikou stáčení.

Jednotky SI, jeden virtuální čas s motorem. Parametry jsou výukové, ne kalibrace.
TCU a ABS/ESP čtou výhradně doručené CAN zprávy, ne přímý stav modelu.
"""

import math
from dataclasses import dataclass

from can_bus import CanBus, encode

WHEELS = ("FL", "FR", "RL", "RR")
RATIOS = {-1: -3.2, 0: 0.0, 1: 3.6, 2: 2.1, 3: 1.4, 4: 1.0, 5: 0.8, 6: 0.65}
SELECTORS = {"P": 0, "R": 1, "N": 2, "D": 3}


def clamp(value, low, high):
    return max(low, min(high, value))


@dataclass(frozen=True)
class VehicleConfig:
    mass_kg: float = 1250.0
    wheel_radius_m: float = 0.30
    wheel_inertia: float = 1.8
    wheelbase_m: float = 2.6
    track_m: float = 1.55
    final_drive: float = 3.9
    drag_area: float = 0.65

    def __post_init__(self):
        if not all(math.isfinite(v) and v > 0 for v in vars(self).values()):
            raise ValueError("Neplatná konfigurace vozidla")


class TransmissionController:
    """Jednoduchý automat 6 stupňů, hystereze a rozepnutí spojky při řazení."""

    def __init__(self):
        self.gear = 0
        self.shift_until = self.last_shift = 0
        self.fault = False

    def tick(self, bus, now):
        ecu, chassis, selector = (bus.read(i, now) for i in (0x100, 0x120, 0x130))
        self.fault = not all((ecu, chassis, selector))
        shifting = now < self.shift_until
        desired = self.gear
        if self.fault:
            desired = 0
        elif not shifting:
            choice = selector["selector"]
            if choice in (0, 2):
                desired = 0
            elif choice == 1:
                # Opačný směr až téměř v klidu; při jízdě vpřed zůstává neutrál.
                desired = -1 if chassis["speed_cms"] < 50 else 0
            elif choice == 3:
                if chassis["speed_cms"] < -50:
                    desired = 0
                elif self.gear <= 0:
                    desired = 1
                elif now - self.last_shift >= 800_000:
                    if ecu["rpm"] > 2600 and self.gear < 6:
                        desired += 1
                    elif ecu["rpm"] < 1200 and self.gear > 1:
                        desired -= 1
        if desired != self.gear:
            self.gear = desired
            self.last_shift = now
            self.shift_until = now + 180_000
        bus.send(
            0x200, encode(0x200, gear=self.gear, shifting=int(now < self.shift_until)), "TCU", now
        )


class StabilityController:
    """ABS moduluje tlak podle skluzu; ESP přibrzďuje jedno kolo podle chyby stáčení."""

    def __init__(self):
        self.pressure = [0.0] * 4
        self.abs_active = self.esp_active = self.fault = False

    def tick(self, bus, now, abs_enabled=True, esp_enabled=True):
        wheels, chassis = bus.read(0x110, now), bus.read(0x120, now)
        self.fault = not wheels or not chassis
        self.abs_active = self.esp_active = False
        if self.fault:
            self.pressure = [0.0] * 4
            torque_pct = 100
        else:
            speed = chassis["speed_cms"] / 100
            brake = chassis["brake_permille"] / 1000
            direction = 1 if speed >= 0 else -1
            for i, key in enumerate(("fl_cms", "fr_cms", "rl_cms", "rr_cms")):
                slip = (abs(speed) - wheels[key] / 100 * direction) / max(abs(speed), 1)
                if abs_enabled and abs(speed) > 1 and slip > 0.18 and brake > 0:
                    self.pressure[i] = max(0, self.pressure[i] - 0.25)
                    self.abs_active = True
                else:
                    self.pressure[i] = min(brake, self.pressure[i] + 0.08)
            steer = chassis["steer_mrad"] / 1000
            desired_yaw = speed / 2.6 * math.tan(steer)
            error = desired_yaw - chassis["yaw_mrad_s"] / 1000
            self.esp_active = bool(esp_enabled and abs(speed) > 3 and abs(error) > 0.10)
            if self.esp_active:
                # Kladná korekce stáčení: levé zadní; záporná: pravé zadní.
                wheel = 2 if error > 0 else 3
                self.pressure[wheel] = max(self.pressure[wheel], min(0.65, abs(error)))
            torque_pct = 45 if self.esp_active else 100
        values = dict(zip(("fl", "fr", "rl", "rr"), (round(p * 255) for p in self.pressure)))
        bus.send(
            0x210,
            encode(
                0x210,
                **values,
                abs=int(self.abs_active),
                esp=int(self.esp_active),
                torque_pct=torque_pct,
                fault=int(self.fault),
            ),
            "ABS/ESP",
            now,
        )


def dashboard(bus, now):
    """Palubní přístroje zobrazují pouze to, co opravdu dorazilo po CAN."""
    ecu, chassis, tcu, esc, thermal, body = (
        bus.read(i, now) for i in (0x100, 0x120, 0x200, 0x210, 0x300, 0x310)
    )
    return {
        "can_fault": not all((ecu, chassis, tcu, esc, thermal, body)),
        "rpm": ecu["rpm"] if ecu else None,
        "speed_kmh": abs(chassis["speed_cms"]) * 0.036 if chassis else None,
        "gear": tcu["gear"] if tcu else None,
        "shifting": bool(tcu["shifting"]) if tcu else False,
        "abs": bool(esc["abs"]) if esc else False,
        "esp": bool(esc["esp"]) if esc else False,
        "controller_fault": bool(esc["fault"]) if esc else True,
        "coolant_c": thermal["coolant_dc"] / 10 if thermal else None,
        "oil_kpa": thermal["oil_kpa"] if thermal else None,
        "battery_v": thermal["battery_cv"] / 100 if thermal else None,
        "fuel_pct": body["fuel_permille"] / 10 if body else None,
    }


class VehicleModel:
    def __init__(self, config=VehicleConfig(), start_us=0):
        self.config = config
        self.bus = CanBus()
        self.tcu = TransmissionController()
        self.esc = StabilityController()
        self.speed = self.distance = self.yaw_rate = self.heading = 0.0
        self.ax = self.ay = 0.0
        self.wheel_omega = [0.0] * 4
        self.brake = self.steer = self.grade = 0.0
        self.mu_left = self.mu_right = 0.85
        self.selector = "N"
        self.abs_enabled = self.esp_enabled = True
        self.coolant = 85.0
        self.oil_temp = 80.0
        self.fuel_l = 40.0
        self.time_us = self.next_control_us = start_us
        self.bus.time_us = self.bus.busy_until = self.bus.started_us = start_us
        self.start_us = start_us
        self.gear = 0
        self.shifting = False
        self.engine_load_nm = 0.0
        self.torque_factor = 1.0
        self.drive_torque = [0.0] * 4
        self.brake_pressure = [0.0] * 4
        self.abs_active = self.esp_active = self.can_fault = False
        self.cylinders = 4
        self.last_rpm = self.last_torque = self.last_pedal = self.last_fuel_us = 0.0

    def command(self, data):
        """Validace je atomická; neplatný povel nezmění ani jednu hodnotu."""
        limits = {
            "brake": (0, 1),
            "steer_deg": (-30, 30),
            "grade_pct": (-20, 20),
            "mu_left": (0.05, 1.2),
            "mu_right": (0.05, 1.2),
        }
        switches = {"abs_enabled", "esp_enabled", "can_enabled"}
        if not isinstance(data, dict) or set(data) - (set(limits) | switches | {"selector"}):
            raise ValueError("Neznámý povel vozidla")
        for key, value in data.items():
            if key in limits:
                low, high = limits[key]
                if (
                    type(value) not in (int, float)
                    or not math.isfinite(value)
                    or not low <= value <= high
                ):
                    raise ValueError("Povel mimo rozsah: " + key)
            elif key in switches:
                if type(value) is not bool:
                    raise ValueError("Očekávána logická hodnota: " + key)
            elif not isinstance(value, str) or value not in SELECTORS:
                raise ValueError("Neplatný volič převodovky")
        for key, value in data.items():
            if key == "steer_deg":
                self.steer = math.radians(value)
            elif key == "grade_pct":
                self.grade = value / 100
            elif key == "can_enabled":
                self.bus.enabled = value
            else:
                setattr(self, key, value)

    def _publish(self, now):
        def send(identifier, **values):
            self.bus.send(
                identifier,
                encode(identifier, **values),
                "SENSORS" if identifier != 0x100 else "ECU",
                now,
            )

        bounded = lambda x: round(clamp(x, -32768, 32767))
        send(
            0x100,
            rpm=round(self.last_rpm),
            fuel_us=round(clamp(self.last_fuel_us, 0, 65535)),
            torque_nm=bounded(self.last_torque),
            pedal_permille=round(self.last_pedal * 1000),
        )
        send(
            0x110,
            **dict(
                zip(
                    ("fl_cms", "fr_cms", "rl_cms", "rr_cms"),
                    (bounded(w * self.config.wheel_radius_m * 100) for w in self.wheel_omega),
                )
            ),
        )
        send(
            0x120,
            speed_cms=bounded(self.speed * 100),
            yaw_mrad_s=bounded(self.yaw_rate * 1000),
            steer_mrad=bounded(self.steer * 1000),
            brake_permille=round(self.brake * 1000),
        )
        send(0x130, selector=SELECTORS[self.selector])
        sensors = self.sensors()
        send(
            0x300,
            coolant_dc=round(self.coolant * 10),
            oil_dc=round(self.oil_temp * 10),
            oil_kpa=round(sensors["oil_pressure_kpa"]),
            battery_cv=round(sensors["battery_v"] * 100),
        )
        send(
            0x310,
            fuel_permille=round(self.fuel_l / 50 * 1000),
            maf_dgs=round(sensors["maf_g_s"] * 10),
            ax_cms2=bounded(self.ax * 100),
            ay_cms2=bounded(self.ay * 100),
        )

    def _control(self, now):
        self._publish(now)
        # Řadiče čtou předchozí doručený vzorek. Nové rámce teprve projdou sběrnicí.
        self.tcu.tick(self.bus, now)
        self.esc.tick(self.bus, now, self.abs_enabled, self.esp_enabled)
        tcu, esc = self.bus.read(0x200, now), self.bus.read(0x210, now)
        self.can_fault = not tcu or not esc or self.tcu.fault or self.esc.fault
        self.gear = tcu["gear"] if tcu else 0
        self.shifting = bool(tcu["shifting"]) if tcu else False
        if self.tcu.fault:
            self.gear = 0
        if esc and not esc["fault"] and not self.esc.fault:
            self.brake_pressure = [esc[k] / 255 for k in ("fl", "fr", "rl", "rr")]
            self.torque_factor = esc["torque_pct"] / 100
            self.abs_active, self.esp_active = bool(esc["abs"]), bool(esc["esp"])
        else:
            # Výpadek komunikace ponechá základní hydraulickou brzdu bez ABS/ESP.
            self.brake_pressure = [self.brake] * 4
            self.torque_factor = 1.0
            self.abs_active = self.esp_active = False

    def step(self, dt, rpm, torque_nm, pedal, injection_us, cylinders=4):
        if not math.isfinite(dt) or not 0 < dt <= 0.1 or round(dt * 1e6) < 1:
            raise ValueError("Krok vozidla musí být 1 µs až 100 ms")
        self.cylinders = cylinders
        self.last_rpm, self.last_torque = rpm, torque_nm
        self.last_pedal, self.last_fuel_us = pedal, injection_us
        end = self.time_us + round(dt * 1e6)
        while self.time_us < end:
            if self.time_us >= self.next_control_us:
                self._control(self.time_us)
                self.next_control_us += 10_000
            # Nejvýše 1 ms a vždy hranice dalšího řídicího cyklu.
            next_us = min(end, self.time_us + 1000, self.next_control_us)
            self._physics((next_us - self.time_us) / 1e6)
            self.bus.advance(next_us)
            self.time_us = next_us

    def _physics(self, dt):
        c = self.config
        ratio = RATIOS[self.gear] * c.final_drive
        output_omega = (self.wheel_omega[0] + self.wheel_omega[1]) / 2
        # Spojka přenáší omezený moment podle rozdílu otáček; při řazení je rozepnutá.
        slip = self.last_rpm * math.pi / 30 - output_omega * ratio
        clutch = clamp(slip * 1.8, -150, 150) if ratio and not self.shifting else 0.0
        # V nízkých otáčkách spojku rozepneme, aby výukový model nezhasl při zastavení.
        if self.last_rpm < 650 and clutch > 0:
            clutch *= clamp((self.last_rpm - 400) / 250, 0, 1)
        self.engine_load_nm = clutch
        # Otevřený přední diferenciál: stejný hnací moment vlevo a vpravo.
        axle = clutch * ratio
        self.drive_torque = [axle / 2, axle / 2, 0, 0]
        forces = []
        for i, omega in enumerate(self.wheel_omega):
            side = -1 if i in (0, 2) else 1
            road_speed = self.speed + side * self.yaw_rate * c.track_m / 2
            slip_speed = omega * c.wheel_radius_m - road_speed
            mu = self.mu_left if i in (0, 2) else self.mu_right
            normal = c.mass_kg * 9.81 / 4
            # Nasycená křivka pneumatiky; žádné přímé přikazování otáček kola.
            force = mu * normal * math.tanh(slip_speed / max(0.7, abs(self.speed) * 0.12))
            forces.append(force)
            brake = max(
                self.brake_pressure[i],
                1.0 if self.selector == "P" and abs(self.speed) < 0.5 else 0.0,
            )
            reference = omega if abs(omega) > 0.05 else road_speed
            sign = 1 if reference >= 0 else -1
            brake_torque = brake * 1400 * sign
            new_omega = (
                omega
                + (self.drive_torque[i] - force * c.wheel_radius_m - brake_torque)
                / c.wheel_inertia
                * dt
            )
            if brake > 0 and new_omega * sign < 0:
                new_omega = 0.0
            self.wheel_omega[i] = new_omega
        drag = 0.5 * 1.225 * c.drag_area * self.speed * abs(self.speed)
        rolling = c.mass_kg * 9.81 * 0.012 * math.tanh(self.speed / 0.5)
        self.ax = (sum(forces) - drag - rolling) / c.mass_kg - 9.81 * self.grade
        old_speed = self.speed
        self.speed += self.ax * dt
        if self.brake > 0 and old_speed * self.speed < 0 and abs(old_speed) < 0.1:
            self.speed = 0.0
        self.distance += abs(self.speed) * dt
        desired_yaw = self.speed / c.wheelbase_m * math.tan(self.steer)
        max_yaw = min(self.mu_left, self.mu_right) * 9.81 / max(abs(self.speed), 2)
        tire_yaw = clamp(desired_yaw, -max_yaw, max_yaw)
        brake_yaw = ((forces[1] + forces[3]) - (forces[0] + forces[2])) * c.track_m / 2
        self.yaw_rate += ((tire_yaw - self.yaw_rate) * 3 + brake_yaw / 1800) * dt
        self.heading += self.yaw_rate * dt
        self.ay = self.speed * self.yaw_rate
        running = self.last_rpm > 300
        target_temp = 90 + min(15, max(0, self.last_torque) / 15) if running else 25
        self.coolant += (target_temp - self.coolant) * dt / 90
        self.oil_temp += (self.coolant - self.oil_temp) * dt / 120
        # Pouze odhad spotřeby z dávky a počtu cyklů čtyřválce.
        self.fuel_l = max(
            0,
            self.fuel_l
            - self.last_fuel_us / 1e6 * self.last_rpm / 120 * self.cylinders * 0.003 * dt,
        )

    def sensors(self):
        return {
            "wheel_speed_kmh": dict(
                zip(WHEELS, (w * self.config.wheel_radius_m * 3.6 for w in self.wheel_omega))
            ),
            "vehicle_speed_kmh": self.speed * 3.6,
            "intake_air_c": 25.0,
            "barometric_pressure_kpa": 101.3,
            "fuel_rail_pressure_kpa": 350.0 if self.last_rpm > 0 else 0.0,
            "exhaust_temp_c": 25.0 + min(750, self.last_rpm * 0.06 + max(0, self.last_torque) * 2),
            "steering_deg": math.degrees(self.steer),
            "yaw_rate_deg_s": math.degrees(self.yaw_rate),
            "longitudinal_accel_m_s2": self.ax,
            "lateral_accel_m_s2": self.ay,
            "brake_pressure_bar": dict(zip(WHEELS, (p * 100 for p in self.brake_pressure))),
            "coolant_c": self.coolant,
            "oil_temp_c": self.oil_temp,
            "oil_pressure_kpa": clamp(self.last_rpm * 0.12, 0, 500),
            "battery_v": 14.2 if self.last_rpm > 500 else 12.3,
            "maf_g_s": max(0, self.last_rpm / 60 * 0.04 * (0.2 + self.last_pedal)),
            "fuel_level_l": self.fuel_l,
            "gearbox_input_rpm": self.last_rpm,
            "gearbox_output_rpm": sum(self.wheel_omega[:2])
            / 2
            * 30
            / math.pi
            * self.config.final_drive,
        }

    def snapshot(self):
        return {
            "time_us": self.time_us,
            "speed_kmh": self.speed * 3.6,
            "distance_m": self.distance,
            "selector": self.selector,
            "gear": self.gear,
            "shifting": self.shifting,
            "brake": self.brake,
            "steer_deg": math.degrees(self.steer),
            "grade_pct": self.grade * 100,
            "mu_left": self.mu_left,
            "mu_right": self.mu_right,
            "abs_enabled": self.abs_enabled,
            "esp_enabled": self.esp_enabled,
            "abs_active": self.abs_active,
            "esp_active": self.esp_active,
            "can_fault": self.can_fault,
            "engine_load_nm": self.engine_load_nm,
            "torque_factor": self.torque_factor,
            "differential": {
                "type": "open_front",
                "wheel_torque_nm": dict(zip(WHEELS, self.drive_torque)),
            },
            "sensors": self.sensors(),
            "dashboard": dashboard(self.bus, self.time_us),
            "can": self.bus.snapshot(),
        }
