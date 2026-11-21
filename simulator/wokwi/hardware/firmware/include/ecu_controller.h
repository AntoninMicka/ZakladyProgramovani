#pragma once
/*
 * ECU = elektronická řídicí jednotka motoru.
 * Představ si ji jako dirigenta: podle polohy motoru dává správným součástkám
 * povel „teď začni“ a „teď skonči“.
 *
 * Tento soubor obsahuje rozhodování našeho jednoduchého výukového řadiče:
 *   1. Ze snímače CKP zjistí otáčky a polohu klikového hřídele.
 *   2. Ze snímače CMP zjistí, ve které otáčce pracovního cyklu motor je.
 *   3. Ve vhodné chvíli otevře vstřikovač a začne nabíjet zapalovací cívku.
 *   4. Po stanovené době vstřikovač zavře a nabíjení cívky ukončí.
 *
 * Co je pracovní cyklus? Čtyřtaktní motor střídá sání, stlačení směsi,
 * pracovní zdvih a výfuk. Klikový hřídel se při tom otočí DVAKRÁT:
 *   1 otáčka = 360 stupňů, celý cyklus = 720 stupňů.
 *
 * Důležité jednotky:
 *   rpm = otáčky za minutu; 1000 rpm znamená 1000 otáček za jednu minutu.
 *   us  = mikrosekundy; 1 sekunda = 1 000 000 mikrosekund.
 *   deg = stupně; úhel říká, kam se hřídel právě otočil.
 *
 * Jde o zjednodušené školní demo. Dávka paliva se zatím počítá přímo z pedálu, předstih je
 * přednastavený. Není to hotová jednotka pro skutečné auto. Fyziku motoru počítá simulátor zvlášť;
 * zde pouze čteme události snímačů a rozhodujeme o výstupech.
 */

// Piny a hodnoty ECU_... se generují z JSON konfigurace projektu.
// Tento generovaný soubor ručně neupravujeme: další sestavení by změny přepsalo.
#include "generated_pins.h"
#include <math.h>   // fmod = zbytek po dělení, fabs = velikost čísla bez znaménka.
#include <stdint.h> // uint32_t = celé nezáporné číslo uložené přesně ve 32 bitech.

// struct sdružuje proměnné (paměť řadiče) a funkce (co řadič umí) do jednoho celku.
// Konkrétní řadič se v main.cpp jmenuje ecu, takže například ecu.rpm jsou jeho otáčky.
// Snímek vozidla pro automobilní režim. Všechny členy double udržují jednoduché C ABI.
// Pedál a CKP/CMP nadále vstupují původní cestou. Karosářské veličiny jsou diagnostika.
struct EcuVehicleInputs {
  double map_kpa, maf_g_s, iat_c, baro_kpa, coolant_c, oil_c, oil_kpa;
  double battery_v, rail_kpa, fuel_l, exhaust_c, lambda_value;
  double speed_kmh, wheel_fl, wheel_fr, wheel_rl, wheel_rr;
  double brake, steer_deg, yaw_deg_s, ax, ay;
  double input_rpm, output_rpm, gear, shifting, torque_limit, abs_active, esp_active, can_valid;
  double auxiliary_load_nm, drivetrain_load_nm, cylinders;
  double tps, brake_fl, brake_fr, brake_rl, brake_rr;
};

struct EcuController {
  // last_ckp: čas posledního přijatého zubu CKP.
  // normal_us: odhad běžné doby mezi dvěma sousedními zuby, tedy BEZ velké mezery.
  // cam_time: čas posledního impulzu CMP.
  // edges/cam_edges: počty přijatých impulzů CKP/CMP pro výpis do konzole.
  // errors: počet zjištěných nesrovnalostí; není to počet všech možných poruch.
  uint32_t last_ckp = 0, normal_us = 0, cam_time = 0, edges = 0, cam_edges = 0, errors = 0;

  // Pole je několik políček se společným názvem. Počet políček určuje ECU_CYLINDERS (výchozí jsou
  // čtyři). Počítač je čísluje od NULY: [0] je první válec, [3] je čtvrtý.
  // ..._end uchovává čas, KDY má příslušný výstup skončit.
  uint32_t injector_end[ECU_CYLINDERS] = {}, coil_end[ECU_CYLINDERS] = {};
  // bool má jen dvě hodnoty: true = ano, false = ne.
  // ..._on říká, zda je vstřikovač právě otevřený nebo cívka právě nabíjená.
  bool injector_on[ECU_CYLINDERS] = {}, coil_on[ECU_CYLINDERS] = {};

  // Na začátku nic o poloze motoru nevíme. Příznaky se postupně mění na true:
  // have_ckp  = máme alespoň první údaj z klikového hřídele;
  // gap_seen  = našli jsme výraznou mezeru po vynechaných zubech;
  // synced    = CMP potvrdilo správnou polovinu cyklu, můžeme řídit výstupy;
  // have_phase = máme předchozí úhel pro porovnání „předtím a teď“.
  bool have_ckp = false, gap_seen = false, synced = false, have_phase = false;

  // slot je číslo polohy zubu po mezeře: 0, 1, 2, ...
  // revolution střídá 0 a 1: první nebo druhá otáčka v cyklu dlouhém 720 stupňů.
  unsigned slot = 0, revolution = 0;
  // phase_at_edge je poloha při posledním zubu, last_phase při minulém tick().
  // double je typ pro čísla s desetinnou částí, například úhel 12,5 stupně.
  double rpm = 0, phase_at_edge = 0, last_phase = 0;

  // Pedál je POUZE vstup od řidiče (0 = puštěný, 1 = plně sešlápnutý).
  // Výchozí 1 zachovává plnou dávku při samostatném testu bez připojeného pedálu.
  // Mock i firmware tuto hodnotu přepíšou skutečným vstupem.
  double accelerator = 1;
  // -1 znamená: regulace otáček zatím není zapnutá. Student sem může zapsat svůj cíl.
  double requested_rpm = -1;
  uint32_t injection_us = ECU_INJECTION_US;
  uint32_t last_control_us = 0;
  bool have_control = false;

  bool vehicle_mode = false, vehicle_inputs_valid = false;
  EcuVehicleInputs sensors = {};
  uint32_t sensor_time_us = 0, car_started_us = 0;
  bool car_started = false, overrun_cut = false, rpm_cut = false;
  double idle_integral = 0, lambda_trim = 1, throttle_target = 0.06;
  double ignition_advance_deg = ECU_ADVANCE_DEG;
  uint32_t dwell_us = ECU_DWELL_US, car_faults = 0;
  // 0 jízda, 1 volnoběh, 2 dojezd bez paliva, 3 omezovač, 4 ochranné vypnutí, 5 nouzový režim.
  unsigned car_state = 0;

  static double limit(double value, double low, double high) {
    return fmax(low, fmin(high, value));
  }

  void set_vehicle_inputs(const EcuVehicleInputs &input, uint32_t now, bool enabled) {
    if (enabled != vehicle_mode) {
      idle_integral = 0;
      lambda_trim = 1;
      overrun_cut = rpm_cut = car_started = false;
      throttle_target = 0.06;
    }
    vehicle_mode = enabled;
    sensors = input;
    sensor_time_us = now;
    vehicle_inputs_valid = true;
    if (!enabled) {
      ignition_advance_deg = ECU_ADVANCE_DEG;
      dwell_us = ECU_DWELL_US;
    }
  }

  // Automobilní režim: APP -> vzduch/moment, samostatný volnoběh a dávka z MAF.
  // Kalibrace odpovídá lokálnímu výukovému modelu, nikoli skutečnému motoru.
  void update_vehicle_control(uint32_t now) {
    if (!car_started) {
      car_started = true;
      car_started_us = now;
    }
    double dt = have_control ? limit((uint32_t)(now - last_control_us) / 1e6, 0.001, 0.1) : 0.01;
    const EcuVehicleInputs &v = sensors;
    car_faults = 0;
    bool core = vehicle_inputs_valid && (uint32_t)(now - sensor_time_us) <= 300000;
    // Neplatné hodnoty nesmějí propadnout do lround či integrátoru jako NaN.
    const double raw[] = {v.tps,
                          v.brake_fl,
                          v.brake_fr,
                          v.brake_rl,
                          v.brake_rr,
                          v.map_kpa,
                          v.maf_g_s,
                          v.iat_c,
                          v.baro_kpa,
                          v.coolant_c,
                          v.oil_c,
                          v.oil_kpa,
                          v.battery_v,
                          v.rail_kpa,
                          v.fuel_l,
                          v.exhaust_c,
                          v.lambda_value,
                          v.speed_kmh,
                          v.wheel_fl,
                          v.wheel_fr,
                          v.wheel_rl,
                          v.wheel_rr,
                          v.brake,
                          v.steer_deg,
                          v.yaw_deg_s,
                          v.ax,
                          v.ay,
                          v.input_rpm,
                          v.output_rpm,
                          v.gear,
                          v.shifting,
                          v.torque_limit,
                          v.abs_active,
                          v.esp_active,
                          v.can_valid,
                          v.auxiliary_load_nm,
                          v.drivetrain_load_nm,
                          v.cylinders};
    for (unsigned i = 0; i < sizeof(EcuVehicleInputs) / sizeof(double); ++i)
      if (!isfinite(raw[i]))
        core = false;
    core = core && v.map_kpa >= 5 && v.map_kpa <= 150 && v.iat_c > -50 && v.iat_c < 150 &&
           v.baro_kpa > 40 && v.baro_kpa < 120 && v.cylinders >= 1 && v.cylinders <= 16 &&
           v.coolant_c >= -40 && v.coolant_c <= 150 && v.battery_v > 0;
    if (!core) {
      car_faults = 1;
      injection_us = 0;
      throttle_target = 0;
      car_state = 4;
      requested_rpm = -1;
      idle_integral = 0;
      return;
    }
    bool can_ok = v.can_valid > 0.5;
    if (!can_ok)
      car_faults |= 2;
    double idle_goal = 850 + limit((65 - v.coolant_c) * 4, 0, 250);
    double pedal = accelerator;
    if (v.brake > 0.15)
      pedal = 0; // Brzda má přednost před současně sešlápnutým plynem.
    bool idle = pedal < 0.03 && (fabs(v.speed_kmh) < 7 || v.gear == 0);
    requested_rpm = idle ? idle_goal : -1;
    double authority = can_ok ? limit(v.torque_limit, 0, 1) : 0.20;
    if (v.shifting > 0.5)
      authority = fmin(authority, 0.15);
    if (v.coolant_c > 105)
      authority = fmin(authority, limit((125 - v.coolant_c) / 20, 0, 1));
    if (v.oil_c > 140 || v.exhaust_c > 900) {
      authority = fmin(authority, 0.4);
      car_faults |= 8;
    }
    if (v.battery_v < 10) {
      authority = fmin(authority, 0.25);
      car_faults |= 16;
    }
    // Kontrola prokluzu doplňuje momentový požadavek ESP; není to druhé řízení brzd.
    double front = (fabs(v.wheel_fl) + fabs(v.wheel_fr)) / 2;
    double rear = (fabs(v.wheel_rl) + fabs(v.wheel_rr)) / 2;
    double road = fmax(fabs(v.speed_kmh), rear);
    if (road > 10 && front > road * 1.25 + 2 && pedal > 0.05) {
      authority = fmin(authority, 0.5);
      car_faults |= 64;
    }
    // Veličiny podvozku a hřídelí slouží pro věrohodnost dat, ne pro umělé obohacování.
    if (fabs(v.steer_deg) > 35 || fabs(v.yaw_deg_s) > 200 || fabs(v.ax) > 30 || fabs(v.ay) > 30 ||
        v.tps < 0 || v.tps > 1 || v.brake_fl < 0 || v.brake_fl > 100 || v.brake_fr < 0 ||
        v.brake_fr > 100 || v.brake_rl < 0 || v.brake_rl > 100 || v.brake_rr < 0 ||
        v.brake_rr > 100 || fabs(v.input_rpm - rpm) > 2000 || fabs(v.output_rpm) > 20000 ||
        v.gear < -1 || v.gear > 6 || v.abs_active < 0 || v.abs_active > 1 || v.esp_active < 0 ||
        v.esp_active > 1)
      car_faults |= 128;
    double idle_error = idle_goal - rpm;
    double feedforward =
        0.02 + limit(v.auxiliary_load_nm + fmax(0, v.drivetrain_load_nm), 0, 120) / 600;
    double idle_open = limit(feedforward + idle_error * 0.00045 + idle_integral, 0, 0.6);
    if (idle && !overrun_cut && authority > 0.4) {
      double candidate = limit(idle_integral + idle_error * dt * 0.00012, -0.12, 0.35);
      // Anti-windup: integrátor neroste do nasycení na horním ani dolním limitu.
      if ((idle_open > 0 && idle_open < 0.6) || (idle_open <= 0 && idle_error > 0) ||
          (idle_open >= 0.6 && idle_error < 0))
        idle_integral = candidate;
    } else
      idle_integral *= fmax(0, 1 - dt * 2);
    throttle_target = limit(fmax(pedal * authority, idle ? idle_open : 0), 0, 1);
    if (!can_ok)
      throttle_target = fmin(throttle_target, 0.20);
    if (v.shifting > 0.5)
      throttle_target = fmin(throttle_target, 0.10);
    double rpm_limit = v.gear == 0 ? 4000 : 6500;
    if (rpm > rpm_limit)
      rpm_cut = true;
    if (rpm < rpm_limit - 250)
      rpm_cut = false;
    if (pedal < 0.02 && fabs(v.speed_kmh) > 7 && v.gear != 0 && v.shifting < 0.5) {
      if (rpm > 1400)
        overrun_cut = true;
      if (rpm < 1100)
        overrun_cut = false;
    } else
      overrun_cut = false;
    bool oil_fault = (uint32_t)(now - car_started_us) > 2000000 && rpm > 1100 && v.oil_kpa < 60;
    bool shutdown = oil_fault || v.coolant_c >= 125 || v.fuel_l <= 0 || v.rail_kpa < 80;
    if (oil_fault)
      car_faults |= 4;
    if (v.fuel_l <= 0)
      car_faults |= 256;
    if (v.rail_kpa < 80)
      car_faults |= 512;
    if (v.coolant_c >= 125)
      car_faults |= 8;
    // Air charge: MAF jako hlavní zdroj, MAP/IAT/barometr jako kontrola a fallback.
    double density = 1.184 * (v.map_kpa / v.baro_kpa) * (298.15 / (v.iat_c + 273.15));
    double air_map = (0.0005 * v.cylinders) * density * 1000 * 0.80 * fmax(rpm, 400) / 120;
    double air = v.maf_g_s;
    if (air <= 0 || air > 250 || fabs(air - air_map) > fmax(3, air_map * 0.8)) {
      air = air_map;
      car_faults |= 32;
    }
    bool closed_loop = v.coolant_c > 65 && !idle && pedal > 0.03 && !overrun_cut && !rpm_cut &&
                       !shutdown && v.shifting < 0.5 && (uint32_t)(now - car_started_us) > 3000000;
    if (v.lambda_value >= 0.6 && v.lambda_value <= 1.6 && closed_loop)
      lambda_trim = limit(lambda_trim + (v.lambda_value - 1) * dt * 0.08, 0.90, 1.10);
    double enrichment = 1 + limit((60 - v.coolant_c) / 400, 0, 0.20);
    double per_second = fmax(rpm, 400) / 120 * v.cylinders;
    double pressure = sqrt(limit(v.rail_kpa, 80, 600) / 350);
    double deadtime = limit(0.50 + (14.2 - v.battery_v) * 0.07, 0.35, 1.10);
    double pulse_ms =
        air / (14.7 * per_second * 8.0 * pressure) * 1000 * lambda_trim * enrichment + deadtime;
    // Reálná délka pulzu se musí vejít do příslušného pracovního cyklu.
    double max_pulse = fmin(12.0, 120000 / fmax(rpm, 400) * 0.75);
    if (shutdown || rpm_cut || overrun_cut) {
      injection_us = 0;
      if (shutdown || rpm_cut)
        throttle_target = 0;
      car_state = shutdown ? 4 : rpm_cut ? 3 : 2;
      idle_integral = 0;
    } else {
      injection_us = (uint32_t)lround(limit(pulse_ms, 0, max_pulse) * 1000);
      car_state = !can_ok ? 5 : idle ? 1 : 0;
    }
    ignition_advance_deg = (v.exhaust_c > 900 || v.coolant_c > 110) ? 8 : 15;
    dwell_us = (uint32_t)lround(limit(2000 * 14.2 / v.battery_v, 1500, 3500));
  }

  void set_accelerator(double position) {
    accelerator = isfinite(position) ? fmax(0, fmin(1, position)) : 0;
  }

  // TPS kanál zde ve výukovém zapojení přenáší polohu pedálu. Napětí mezi
  // kalibrovaným minimem a maximem převedeme na číslo 0..1. V Mock přijde přímo.
  void set_accelerator_adc(unsigned raw, unsigned maximum) {
    double volts = maximum ? raw * ECU_ADC_REFERENCE_V / maximum : 0;
    set_accelerator((volts - ECU_PEDAL_MIN_V) / (ECU_PEDAL_MAX_V - ECU_PEDAL_MIN_V));
  }

  bool je_nula(double hodnota, double tolerance = 0.000001) {
    return fabs(hodnota) <= tolerance;
  }

  // === MÍSTO PRO STUDENTSKÝ ÚKOL: ROZHODOVÁNÍ O PALIVU ===
  // Tato funkce je stejná v Mock i na desce a volá se každých 10 ms simulačního času.
  // Vstupy: accelerator = poloha pedálu 0..1, rpm = otáčky změřené z CKP.
  // Výstup: injection_us = požadovaná délka vstřiku v mikrosekundách.
  // now je aktuální čas v us; může se hodit pro budoucí regulátor.
  //
  // Pedál určí cíl, rozdíl proti změřeným otáčkám mění dávku po malých krocích.
  // Otáčky ovlivňujeme jen palivem, nikoli přepisováním rpm.
  void update_control(uint32_t now) {
    (void)now;
    requested_rpm = 800.0 + accelerator * (3000.0 - 800.0);
    double chyba_otacek = requested_rpm - rpm;

    // Počítáme se znaménkem: uint32_t by při odečtení pod nulou přeteklo.
    double davka_us = injection_us;
    if (!je_nula(chyba_otacek, 10.0)) {
      if (chyba_otacek > 0.0)
        davka_us += 5.0;
      else
        davka_us -= 5.0;
    }
    // Nejprve omezíme rozsah, teprve potom převedeme na nezáporné celé číslo.
    injection_us = (uint32_t)lround(fmax(0.0, fmin(20000.0, davka_us)));
  }

  // Převod úhlu do jednoho cyklu: výsledek bude od 0 do méně než 720 stupňů.
  // Podobně jako hodiny po 12 zase ukážou 1, motor po 720 stupních začne nový cyklus.
  // Příklady: wrap(730) = 10; wrap(-15) = 705.
  // static zde znamená, že funkce nepotřebuje proměnné konkrétního řadiče.
  static double wrap(double angle) {
    double r = fmod(angle, 720);
    return r < 0 ? r + 720 : r; // Zápornému výsledku přidáme celý cyklus.
  }

  // CMP je snímač vačkového hřídele. Jeho značka pomůže rozlišit obě otáčky kliky.
  // Funkce dostane čas impulzu v mikrosekundách. now znamená anglicky „teď“.
  void cam(uint32_t now) {
    cam_time = now;
    cam_edges++; // ++ znamená „zvětši o jednu“.
    // Z jediné značky CMP ještě polohu nespočítáme. Potřebujeme i zuby a mezeru CKP.
    // ! znamená „ne“, || znamená „nebo“. return ukončí tuto funkci.
    if (!have_ckp || !normal_us || !gap_seen)
      return;

    // Poloha zubu = jeho číslo krát rozteč zubů. Pro 60 poloh je rozteč 360/60 = 6°.
    // Od posledního zubu už uběhl nějaký čas, proto přičteme odhad dalšího otočení.
    // Proč 6 * rpm? Jedna otáčka má 360° a minuta 60 s: 360 / 60 = 6.
    // Například při 1000 rpm ujede klika za 1 ms úhel 1000 * 6 * 0,001 = 6°.
    // Zápis 1e6 je číslo 1 000 000: převádíme mikrosekundy na sekundy.
    double angle = slot * (360.0 / ECU_TEETH) + (now - last_ckp) * 6 * rpm / 1e6;

    // Porovnáme polohu s očekávanou značkou CMP. Rozdíl převedeme přibližně
    // do rozsahu -180 až +180°, aby například 359° a 1° byly blízko sebe.
    // Číslo 540 = 360 + 180 pomáhá správně přetočit výpočet přes nulu.
    double delta = fmod(angle - ECU_CMP_REFERENCE + 540, 360) - 180;
    // Tolerujeme odchylku menší než dvě rozteče zubů; u kola s 60 polohami je to 12°.
    // Je to pravidlo našeho jednoduchého dekodéru, nikoli záruka přesnosti motoru.
    if (fabs(delta) < 2 * 360.0 / ECU_TEETH) {
      // Reference 0..359 patří do první otáčky, 360..719 do druhé.
      revolution = ECU_CMP_REFERENCE >= 360;
      phase_at_edge = revolution * 360 + slot * (360.0 / ECU_TEETH);
      synced = true;
    } else {
      // CMP přišlo jinde, než čekáme: synchronizaci raději zrušíme a chybu započítáme.
      synced = false;
      errors++;
    }
  }

  // CKP je snímač klikového hřídele: kolem něj procházejí zuby ozubeného kola.
  // Výchozí kolo „60-2“ má 60 možných poloh, ale dva zuby chybějí.
  // Snímač proto uvidí 58 zubů a jednou za otáčku delší mezeru jako orientační značku.
  void crank(uint32_t now) {
    edges++;
    if (!have_ckp) {
      // První čas si jen uložíme. K měření ROZDÍLU potřebujeme dva časy.
      have_ckp = true;
      last_ckp = now;
      return;
    }
    // interval = jak dlouho trvala cesta od minulého zubu k tomuto.
    // Odčítání nezáporných 32bitových časů funguje i přes přetočení micros(),
    // pokud mezi měřeními neuplyne celý jeho rozsah (asi 71,6 minuty).
    uint32_t interval = now - last_ckp;
    if (!interval)
      return; // Dva stejné časy by později způsobily dělení nulou.
    if (normal_us && interval < normal_us * .45) {
      // Méně než 45 % obvyklé doby: podezřele brzký impulz, třeba rušení.
      // Nezměníme last_ckp, protože tento impulz nepovažujeme za platný zub.
      errors++;
      return;
    }
    // Více než 180 % obvyklé doby považujeme za možnou mezeru chybějících zubů.
    bool gap = normal_us && interval > normal_us * 1.8;
    if (gap) {
      // U 60-2 přeskočíme dvě chybějící polohy: vzdálenost mezi skutečnými zuby
      // je TŘIKRÁT běžná rozteč. Např. 1000 us -> očekávaná mezera 3000 us.
      double expected = (ECU_MISSING + 1) * normal_us;
      // Povolíme odchylku 35 % očekávané mezery. Příliš jiný interval je chyba.
      if (fabs(interval - expected) > expected * .35) {
        errors++;
        synced = false;
      }
      revolution ^= 1; // Přepne 0 na 1 a 1 na 0: začíná další otáčka kliky.
      slot = 0;        // První zub po dlouhé mezeře je naše poloha číslo 0.
      gap_seen = true;
    } else {
      // Vyhlazení měření: minulému odhadu dáme váhu 3, novému měření váhu 1.
      // Například (1000 * 3 + 1040) / 4 = 1010 us. Malé výkyvy tolik necukají RPM.
      // Při prvním takovém měření ještě minulý odhad nemáme, vezmeme celý interval.
      normal_us = normal_us ? (normal_us * 3 + interval) / 4 : interval;
      slot++;
      if (slot >= ECU_TEETH - ECU_MISSING) {
        // Vidíme více běžných zubů, než jsme čekali před mezerou.
        // Číslo polohy udržíme v rozsahu kola, ale jistotu o cyklu zrušíme.
        slot %= ECU_TEETH; // %= uloží zbytek po dělení.
        errors++;
        synced = false;
      }
    }
    last_ckp = now;
    // Minuta má 60 000 000 us. Doba jedné otáčky = počet poloh * doba jedné rozteče.
    // Příklad: 60 poloh * 1000 us = 60 000 us/otáčku; 60 000 000 / 60 000 = 1000 rpm.
    // U kola 60-2 dělíme 60, nikoli 58: dvě polohy existují, jen na nich nejsou zuby.
    rpm = normal_us ? 60000000.0 / (ECU_TEETH * normal_us) : 0;
    phase_at_edge = revolution * 360 + slot * (360.0 / ECU_TEETH);
  }

  // Výstupy neovládáme konkrétním Arduino příkazem přímo zde.
  // Dostaneme pomocnou funkci write, která umí povel opravdu poslat na správný pin.
  // Díky tomu stejný řadič testujeme i na počítači bez připojené desky.
  // template <class Write> říká překladači: „typ této pomocné funkce doplň při použití“.
  template <class Write> void stop(Write write) {
    for (unsigned i = 0; i < ECU_CYLINDERS; i++) {
      // První argument write: false = vstřikovač, true = zapalování.
      // ECU_..._ACTIVE je zapnutá úroveň; ! obrátí úroveň na vypnutou.
      // Ne vždy znamená 1 zapnuto: zapojení může používat i opačnou polaritu.
      if (injector_on[i])
        write(false, i, !ECU_INJ_ACTIVE);
      if (coil_on[i])
        write(true, i, !ECU_IGN_ACTIVE);
      injector_on[i] = coil_on[i] = false;
    }
    // Zapomeneme odhady potřebné k řízení. Při novém rozběhu znovu hledáme zuby a CMP.
    // Diagnostické počty errors/edges zde nemažeme, aby byla historie stále vidět.
    synced = false;
    have_phase = false;
    rpm = 0;
    have_ckp = false;
    normal_us = 0;
    gap_seen = false;
    slot = 0;
  }

  // Odpověď na otázku: „Přejeli jsme mezi minulým a nynějším úhlem cílovou značku?“
  // Nestačí porovnat rovnost: při měření po malých krocích můžeme značku přeskočit.
  // Příklad: z 718° na 3° jsme přejeli 5° a minuli značku 1°.
  static bool crossed(double before, double after, double target) {
    double distance = wrap(target - before), travel = wrap(after - before);
    // 1e-7 je maličká tolerance 0,0000001° proti zaokrouhlování desetinných čísel.
    // Cíl přesně v minulém bodě znovu nespouštíme. Skok o 180° a více také odmítneme:
    // při tak velkém skoku už nemáme dost jemné sledování pro toto řízení.
    return distance > 1e-7 && distance <= travel + 1e-7 && travel < 180;
  }

  // tick = jeden krátký kontrolní krok. main.cpp ho běžně volá každých 25 us.
  // Nejprve zkontrolujeme snímač, potom konce pulzů a nakonec jejich nové začátky.
  template <class Write> void tick(uint32_t now, Write write) {
    if (!have_control || (uint32_t)(now - last_control_us) >= 10000) {
      if (vehicle_mode)
        update_vehicle_control(now);
      else
        update_control(now);
      // Omezení výstupu zůstává společné i po studentské změně algoritmu.
      if (injection_us > 100000)
        injection_us = 100000;
      last_control_us = now;
      have_control = true;
    }
    if (have_ckp && normal_us && now - last_ckp > normal_us * 5 + 1000) {
      // Watchdog je „hlídač“: CKP dlouho mlčí, motor se mohl zastavit nebo vypadl snímač.
      // Limit = pět běžných roztečí + 1000 us navíc; pojme i běžnou mezeru 60-2.
      stop(write);
      return;
    }
    for (unsigned i = 0; i < ECU_CYLINDERS; i++) {
      // (int32_t) přečte rozdíl jako číslo se znaménkem: záporný = ještě čekáme,
      // nula nebo kladný = termín přišel. Pro naše krátké pulzy to funguje i přes
      // přetočení čítače micros(); neplatilo by to pro libovolně vzdálené termíny.
      if (injector_on[i] && (int32_t)(now - injector_end[i]) >= 0) {
        write(false, i, !ECU_INJ_ACTIVE);
        injector_on[i] = false;
      }
      if (coil_on[i] && (int32_t)(now - coil_end[i]) >= 0) {
        // Při ukončení nabíjení cívky vzniká v zapalování jiskra.
        // Simulace to představuje hranou digitálního signálu.
        write(true, i, !ECU_IGN_ACTIVE);
        coil_on[i] = false;
      }
    }
    // Konce již otevřených pulzů jsme obsloužili i bez synchronizace.
    // Nové pulzy ale bez známé polohy cyklu nebo bez otáčení nezačneme.
    if (!synced || rpm <= 0) {
      have_phase = false;
      return;
    }
    // Mezi zuby žádný nový údaj nepřišel: polohu krátce odhadneme z posledních RPM.
    // Je to jako odhad ujeté vzdálenosti auta podle rychlosti a uplynulého času.
    double phase = wrap(phase_at_edge + (now - last_ckp) * 6 * rpm / 1e6);
    if (have_phase)
      for (unsigned order = 0; order < ECU_CYLINDERS; order++) {
        // Pořadí válců není jejich číselné pořadí. Výchozí je 1, 3, 4, 2.
        // Odečteme 1, protože v polích potřebujeme indexy 0, 2, 3, 1.
        unsigned channel = FIRING_ORDER[order] - 1;
        // Výukový referenční bod pracovního zdvihu příslušného válce.
        // Čtyřválec má body po 720/4 = 180°: 0°, 180°, 360°, 540°.
        double fire = order * 720.0 / ECU_CYLINDERS;
        if (!injector_on[channel] && crossed(last_phase, phase, wrap(fire + 360))) {
          // V tomto demu zahajujeme vstřik půl cyklu (360°) po referenčním bodu.
          // Otevřeme vstřikovač a uložíme budoucí čas jeho zavření.
          // Délku dávky už spočítala update_control(); zde ji pouze načasujeme.
          write(false, channel, ECU_INJ_ACTIVE);
          injector_on[channel] = true;
          injector_end[channel] = now + injection_us;
          if (injection_us == 0) {
            // Nulovou dávku v našem pulzním modelu oznámí dvojice hran bez čekání.
            // Vstřik nezůstane viset do dalšího ticku; nejde o fyzikální model ventilu.
            write(false, channel, !ECU_INJ_ACTIVE);
            injector_on[channel] = false;
          }
        }
        // Cívka potřebuje nejprve nahromadit energii. Době nabíjení se říká dwell.
        // Nabíjení proto zahájíme před jiskrou; jiskru chceme ještě o předstih dříve
        // než referenční bod fire. Výchozí předstih je 15°, dwell je 2000 us = 2 ms.
        // Při 1000 rpm se za 2 ms otočí klika o 12°: start nabíjení je 15 + 12 = 27°
        // před fire. wrap převede například -27° na 693° předchozího cyklu.
        double charge = wrap(fire - ignition_advance_deg - dwell_us * 6 * rpm / 1e6);
        if (!coil_on[channel] && crossed(last_phase, phase, charge)) {
          write(true, channel, ECU_IGN_ACTIVE);
          coil_on[channel] = true;
          coil_end[channel] = now + dwell_us;
        }
      }
    // Zapamatujeme si úhel pro další porovnání. První tick po synchronizaci
    // pouze vytvoří tento výchozí bod; nezačne zpětně spouštět zmeškané pulzy.
    last_phase = phase;
    have_phase = true;
  }
};
