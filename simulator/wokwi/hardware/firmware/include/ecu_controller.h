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
 * Jde o zjednodušené školní demo. Dávka paliva a předstih jsou přednastavené.
 * Není to hotová jednotka pro skutečné auto. Fyziku motoru počítá simulátor
 * zvlášť; zde pouze čteme události snímačů a rozhodujeme o výstupech.
 */

// Piny a hodnoty ECU_... se generují z JSON konfigurace projektu.
// Tento generovaný soubor ručně neupravujeme: další sestavení by změny přepsalo.
#include "generated_pins.h"
#include <math.h>   // fmod = zbytek po dělení, fabs = velikost čísla bez znaménka.
#include <stdint.h> // uint32_t = celé nezáporné číslo uložené přesně ve 32 bitech.

// struct sdružuje proměnné (paměť řadiče) a funkce (co řadič umí) do jednoho celku.
// Konkrétní řadič se v main.cpp jmenuje ecu, takže například ecu.rpm jsou jeho otáčky.
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
          // Výchozích 3000 us = 3 ms; dávku zde nepočítáme z ADC ani ze zatížení.
          write(false, channel, ECU_INJ_ACTIVE);
          injector_on[channel] = true;
          injector_end[channel] = now + ECU_INJECTION_US;
        }
        // Cívka potřebuje nejprve nahromadit energii. Době nabíjení se říká dwell.
        // Nabíjení proto zahájíme před jiskrou; jiskru chceme ještě o předstih dříve
        // než referenční bod fire. Výchozí předstih je 15°, dwell je 2000 us = 2 ms.
        // Při 1000 rpm se za 2 ms otočí klika o 12°: start nabíjení je 15 + 12 = 27°
        // před fire. wrap převede například -27° na 693° předchozího cyklu.
        double charge = wrap(fire - ECU_ADVANCE_DEG - ECU_DWELL_US * 6 * rpm / 1e6);
        if (!coil_on[channel] && crossed(last_phase, phase, charge)) {
          write(true, channel, ECU_IGN_ACTIVE);
          coil_on[channel] = true;
          coil_end[channel] = now + ECU_DWELL_US;
        }
      }
    // Zapamatujeme si úhel pro další porovnání. První tick po synchronizaci
    // pouze vytvoří tento výchozí bod; nezačne zpětně spouštět zmeškané pulzy.
    last_phase = phase;
    have_phase = true;
  }
};
