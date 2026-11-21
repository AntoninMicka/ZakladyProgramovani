"""Automobilní regulace přes skutečné C++ pulzy, nikoli druhý Python regulátor."""

import math
import unittest
from contextlib import contextmanager

from bridge import MockBridge
from engine import Engine
from native_ecu import VEHICLE_FIELDS


@contextmanager
def bench(pedal=0.4, rpm=2000, overrides=None):
    engine = Engine(vehicle=True)
    engine.model.command({"throttle": pedal})
    if rpm is not None:
        engine.model.command({"rpm": rpm})
    original = engine.vehicle.ecu_inputs
    engine.vehicle.ecu_inputs = lambda model: {**original(model), **(overrides or {})}
    bridge = MockBridge(engine)
    try:
        bridge.start()
        yield engine, bridge
    finally:
        bridge.close()


def advance(engine, seconds):
    for _ in range(round(seconds / engine.dt)):
        engine.step()


class AutomotiveEcuTests(unittest.TestCase):
    def test_idle_recovers_load_step_without_fixed_rpm(self):
        with bench(pedal=0, rpm=None) as (e, b):
            advance(e, 8)
            self.assertAlmostEqual(e.model.rpm, 850, delta=25)
            e.model.command({"load_nm": 30})
            advance(e, 12)
            self.assertAlmostEqual(e.model.rpm, 850, delta=35)
            self.assertEqual(b.diagnostics()["controller"]["car_state"], 1)
            self.assertIsNone(e.model.target_rpm)

    def test_pedal_requests_torque_not_global_rpm_target(self):
        pulses = []
        for pedal in (0.2, 0.8):
            with bench(pedal=pedal) as (e, b):
                advance(e, 1)
                d = b.diagnostics()["controller"]
                self.assertTrue(d["vehicle_mode"])
                self.assertIsNone(d["requested_rpm"])
                self.assertEqual(d["car_state"], 0)
                pulses.append(d["injection_us"])
        self.assertGreater(pulses[1], pulses[0] * 1.6)

    def test_lambda_and_maf_are_coherent_with_air_path_and_fuel(self):
        with bench() as (e, b):
            advance(e, 5)
            s = e.snapshot()
            self.assertAlmostEqual(s["lambda_value"], 1, delta=0.08)
            self.assertGreater(s["maf_g_s"], 0)
            self.assertNotEqual(s["tps"], s["throttle"])  # Mechanická klapka není přímo APP.
            self.assertLess(abs(s["tps"] - 0.4), 0.02)
            self.assertGreater(s["injector_ms"], s["effective_injection_ms"])
            self.assertTrue(0.9 <= b.diagnostics()["controller"]["lambda_trim"] <= 1.1)

    def test_pressure_voltage_compensation_matches_plant(self):
        states = []
        for overrides in ({"rail_kpa": 350, "battery_v": 14.2}, {"rail_kpa": 200, "battery_v": 10}):
            with bench(overrides=overrides) as (e, b):
                advance(e, 1)
                states.append(
                    (
                        b.diagnostics()["controller"]["injection_us"],
                        e.model.effective_injection_ms(),
                    )
                )
        self.assertGreater(states[1][0], states[0][0])
        self.assertAlmostEqual(states[0][1], states[1][1], delta=0.06)

    def test_cold_idle_and_lambda_trim_are_bounded(self):
        with bench(pedal=0, rpm=None, overrides={"coolant_c": 20}) as (e, b):
            advance(e, 10)
            self.assertEqual(b.diagnostics()["controller"]["requested_rpm"], 1030)
            self.assertAlmostEqual(e.model.rpm, 1030, delta=40)
        with bench(overrides={"lambda_value": 1.12}) as (e, b):
            advance(e, 8)
            self.assertGreater(b.diagnostics()["controller"]["lambda_trim"], 1.02)
            self.assertLessEqual(b.diagnostics()["controller"]["lambda_trim"], 1.10)

    def test_maf_fallback_and_plausibility_checks(self):
        with bench(overrides={"maf_g_s": 0, "steer_deg": 99, "brake_fl": 101}) as (e, b):
            advance(e, 1)
            d = b.diagnostics()["controller"]
            self.assertTrue(d["car_faults"] & 32)
            self.assertTrue(d["car_faults"] & 128)
            self.assertGreater(d["injection_us"], 0)

    def test_shutdown_empty_tank_overheat_rail_oil_and_invalid_sensor(self):
        for overrides, flag, seconds in (
            ({"fuel_l": 0}, 256, 0.2),
            ({"coolant_c": 130}, 8, 0.2),
            ({"rail_kpa": 20}, 512, 0.2),
            ({"oil_kpa": 0}, 4, 2.3),
            ({"iat_c": float("nan")}, 1, 0.2),
        ):
            with self.subTest(overrides=overrides), bench(overrides=overrides) as (e, b):
                advance(e, seconds)
                d = b.diagnostics()["controller"]
                self.assertEqual(d["car_state"], 4)
                self.assertEqual(d["injection_us"], 0)
                self.assertTrue(d["car_faults"] & flag)
                self.assertTrue(math.isfinite(e.model.rpm))

    def test_can_limp_brake_override_and_single_esp_intervention(self):
        for overrides, maximum in (
            ({"can_valid": 0}, 0.2),
            ({"torque_limit": 0.45}, 0.45),
            ({"shifting": 1}, 0.1),
            ({"brake": 1}, 0.1),
        ):
            with self.subTest(overrides=overrides), bench(pedal=1, overrides=overrides) as (e, b):
                advance(e, 0.5)
                self.assertLessEqual(b.diagnostics()["controller"]["throttle_target"], maximum)
                self.assertEqual(e.model.torque_factor, 1.0)

    def test_overrun_cuts_fuel_and_rpm_limiter_has_hysteresis(self):
        with bench(pedal=0.8, rpm=None) as (e, b):
            e.vehicle.command({"selector": "D"})
            advance(e, 12)
            self.assertGreater(e.vehicle.speed * 3.6, 30)
            e.model.command({"throttle": 0})
            advance(e, 1)
            d = b.diagnostics()["controller"]
            self.assertEqual(d["car_state"], 2)
            self.assertEqual(d["injection_us"], 0)
        with bench(pedal=1, rpm=4500) as (e, b):
            advance(e, 0.3)
            self.assertEqual(b.diagnostics()["controller"]["car_state"], 3)
            self.assertEqual(b.diagnostics()["controller"]["injection_us"], 0)
            e.model.command({"rpm": 3500})
            advance(e, 0.3)
            self.assertGreater(b.diagnostics()["controller"]["injection_us"], 0)

    def test_stopped_automatic_holds_idle_with_brake(self):
        with bench(pedal=0, rpm=None) as (e, b):
            e.vehicle.command({"selector": "D", "brake": 1})
            advance(e, 8)
            self.assertAlmostEqual(e.model.rpm, 850, delta=35)
            self.assertLess(abs(e.vehicle.speed), 0.05)
            self.assertLessEqual(e.vehicle.engine_load_nm, 12)
            self.assertEqual(b.diagnostics()["controller"]["car_state"], 1)

    def test_voltage_compensated_coil_pulses_and_hot_exhaust_advance(self):
        with bench(overrides={"battery_v": 11.8, "exhaust_c": 950}) as (e, b):
            advance(e, 1)
            d = b.diagnostics()["controller"]
            self.assertTrue(d["car_faults"] & 8)
            self.assertEqual(d["advance_deg"], 8)
            self.assertGreater(d["dwell_us"], 2000)
            self.assertTrue(e.model.last_dwell_us)
            for pulse in e.model.last_dwell_us.values():
                self.assertTrue(d["dwell_us"] <= pulse <= d["dwell_us"] + 25)
            self.assertAlmostEqual(e.model.ignition_deg, 8, delta=0.5)

    def test_stale_sensor_frame_disables_fuel(self):
        with bench() as (e, b):
            advance(e, 0.5)
            b.controller.advance(e.clock.time_us + 400_000, [], 0.4)
            d = b.diagnostics()["controller"]
            self.assertEqual(d["car_state"], 4)
            self.assertTrue(d["car_faults"] & 1)
            self.assertEqual(d["injection_us"], 0)

    def test_all_vehicle_sensor_fields_cross_abi_and_air_not_double_integrated(self):
        with bench() as (e, b):
            e.model.vehicle_physics = True
            payload = e.vehicle.ecu_inputs(e.model)
            self.assertEqual(set(payload), set(VEHICLE_FIELDS))
            advance(e, 0.1)
            e.model.air_throttle = 0.06
            advance(e, 0.01)
            self.assertGreater(e.model.air_throttle, 0.06)
            self.assertLess(e.model.air_throttle, 0.13)  # 60ms člen, nikoli dvojí integrace.
            e.set_vehicle_enabled(False)
            advance(e, 0.02)
            self.assertFalse(b.diagnostics()["controller"]["vehicle_mode"])
            self.assertFalse(e.model.vehicle_physics)
