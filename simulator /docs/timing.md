# Časování a omezení

## Tři časové osy

Hostitelský wall time pochází z `monotonic()`. Virtuální čas je celé číslo µs
posouvané výhradně `SimulationClock` o pevný krok. ECU/chip používá vlastní
čas Wokwi (`micros()` a `get_sim_nanos()`). RFC2217 neřídí hodiny Wokwi.

Engine vlákno používá wall time pouze k pacingu. Když se OS opozdí, nepřeskočí
virtuální krok ani nezvětší dt. Postupně dohání čas; zaznamenává aktuální a maximální
wall lag. Při `speed=0.5` má každý virtuální krok dvojnásobný wall interval.
Pause zastaví virtuální čas, resume pokračuje; restart obnoví hostitelský model.
MCU se tím nepozastaví ani neresetuje. Režim zpomalení je ověřen pro Mock;
Wokwi nemá v této implementaci lockstep a běží vlastní rychlostí.

Pro stejnou konfiguraci a stejný sled povelů vložených na hranicích virtuálních
kroků je výpočet reprodukovatelný. Čas příchodu živého TCP povelu deterministický
není. Události nesou vlastní značky a měří se jejich opoždění; model historii nevrací.

## Hostitelské signály

Úhel se integruje lichoběžníkově z počátečních a koncových RPM:
`delta_angle = (rpm_before + rpm_after) / 2 * 6 * dt`.
Moment je zjednodušená funkce plynu, paliva, předstihu a počtu válců.
`alpha = (torque - load - friction) / inertia`, převod na změnu RPM je `60/(2π)`.
To nenahrazuje termodynamiku a skutečnou charakteristiku motoru.

CKP používá první N−missing zubů v každé otáčce, duty 50 % rozteče.
U 60-2 jsou zuby 58 a 59 vynechány: mezi posledním a prvním náběhem je trojnásobná
rozteč. CMP impulzy se opakují po 720°, polohy i šířka jsou konfigurovatelné;
překryv je odmítnut. Počáteční úrovně jsou ve snapshotu.
Hrany se vyhledávají podle překročených úhlů, nikoli podle konstantního intervalu.
Jejich čas se lineárně interpoluje uvnitř integračního úseku a zaokrouhlí na µs.
Při měnící se rychlosti je to aproximace; menší krok zmenšuje chybu. Testy dokazují
geometrii a konstantní RPM, nikoli obecnou submikrosekundovou přesnost.

## Lokální virtuální piny

Custom Chip integruje poslední RPM v desetimikrosekundovém časovači Wokwi.
Každý tick nastaví CKP/CMP z vlastního úhlu. U konstantních RPM tedy očekáváme
kvantování hran do 10 µs plus numerické zaokrouhlení; toto je návrhové očekávání,
ne naměřená přesnost Wokwi. Změny RPM se aplikují až po doručení lokálního UART
příkazu. Geometrie demo chipu je pevně 60-2, CMP 0–12°; konfigurace Pythonu
se do chipu automaticky nepřenáší.

TCP doručení neurčuje okamžik jednotlivých hran. Nezaručujeme však shodu fáze
chipu s motorem v Pythonu. Pravidelná RPM telemetrie je lokální extrapolace,
nikoli synchronizace virtuálních hodin. Obousměrná cesta je podporovanými API:
host RFC2217 → UART0 MCU → UART1 chip → timer/GPIO; výstupy ECU se vracejí přes
pin_watch → lokální UART → MCU → JSON/RFC2217. Dokumentované Chips API nabízí
časovače, piny, analog a UART; návrh nevyužívá nedoložené externí síťové API chipu.

## Diagnostika

ECU odpovídá na sekvenci `engine_state` zprávou `clock_sync` s vlastním časem.
Host počítá RTT pomocí monotonic wall time a ukládá nejvýše 64 čekajících echo.
`ecu_offset_us = ecu_time_us - simulation_time_us_odeslaného_stavu`.
`ecu_drift_us` je změna tohoto rozdílu vůči první odpovědi daného spojení.
Jde o pozorovaný rozdíl časových os; obsahuje rozdíl epoch, tempo, latenci a zpracování.
Není to odhad jednosměrné latence ani NTP synchronizace. Po reconnectu se baseline zruší.
Telemetrie ukládá i ECU time, připojení, počty chyb, zahozené rámce,
pozdní události, jejich maximální stáří a ztracené hostitelské hrany.

## Souběh a paměť

Model a hodiny obsluhuje Engine vlákno pod zámkem. Zvenčí se čte kopie snapshotu;
I/O vlákno pouze vkládá povely. Žádný síťový read/write není v Engine kroku.
Fronty povelů, čekajících událostí a hran mají samostatně nejvýše 4096 položek.
Přeplnění povelů vyvolá BufferError a bridge je zaznamená; přeplnění hran zvyšuje
čítač ztrát. Odchozí transportní fronta má 4 rámce, nedostupnému serveru se neukládají.
Při přerušení se neodeslané rámce zruší. Vstupní řádek je omezen na 16 KiB;
při backlogu pySerial větším než 64 KiB se spojení uzavře. Interní buffering
pySerialu není pevně alokovaný, tato kontrola jej pravidelně hlídá z workeru.

Připojení se obnovuje po 0.5 s. Při uzavření se přeruší port a zastaví worker;
probíhající TCP/RFC vyjednávání může čekat na timeouty knihovny. Supervisor čeká
nejvýše 20 s na transport a hlásí chybu, pokud se neukončí. Vlastní nový backend
musí implementovat přerušitelné `close()` a omezené `read/write/open`.
Chyba připojení nikdy nevolá blokující I/O z modelu.

Budoucí přesný režim vyžaduje ověřený backend pro řízení MCU času nebo lokální
přehrávač předem datovaných bloků s handshake epochy, lookahead, potvrzením přijetí
a odmítáním opožděných událostí. Takový režim zde není vydáván za hotový HIL.
CAN/OBD, klepání, emise, GUI, kalibrační mapy a model startéru jsou mimo tuto fázi.
