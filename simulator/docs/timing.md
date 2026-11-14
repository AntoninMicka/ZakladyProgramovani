# Časování a omezení

## Tři časové osy

Hostitelský wall time pochází z `monotonic()`. Virtuální čas je celé číslo µs
posouvané výhradně `SimulationClock` o pevný krok. ECU/chip používá vlastní
čas Wokwi (`micros()` a `get_sim_nanos()`). RFC2217 neřídí hodiny Wokwi.

Engine vlákno používá wall time pouze k pacingu. Když se OS opozdí, nepřeskočí
virtuální krok ani nezvětší dt. Zpoždění do 250 ms postupně dohání; nad tímto prahem obnoví wall deadline
a zvýší `pacing_resets`. Virtuální kroky nepřeskakuje. Zaznamenává aktuální
a maximální wall lag. Při `speed=0.5` má každý virtuální krok dvojnásobný wall interval.
Pause zastaví virtuální čas, resume pokračuje; restart obnoví hostitelský model.
MCU se tím nepozastaví ani neresetuje. Režim zpomalení je ověřen pro Mock;
Wokwi nemá v této implementaci lockstep a běží vlastní rychlostí.

Pro stejnou konfiguraci a stejný sled povelů vložených na hranicích virtuálních
kroků je výpočet reprodukovatelný. Čas příchodu živého TCP povelu deterministický
není. Události nesou vlastní značky a měří se jejich opoždění; model historii nevrací.

## Hostitelské signály

Úhel se integruje lichoběžníkově z počátečních a koncových RPM:
`delta_angle = (rpm_before + rpm_after) / 2 * 6 * dt`.
Moment je zjednodušená funkce skutečné dávky paliva, předstihu a počtu válců.
Pedál je vstup ECU; fyzikální model jím moment znovu nenásobí.
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
příkazu. Geometrie legacy chipu se generuje z `engine_config.json` skriptem
`wokwi/configure_legacy.py`; PlatformIO ji regeneruje před překladem. Po změně
JSON je nutné znovu sestavit také WASM. Kontrolor VCD čte stejný JSON nebo
hardwarový profil předaný přes `--config`.

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
CAN/OBD, klepání, emise, kalibrační mapy a model startéru zůstávají mimo tuto fázi.
Na následnou žádost byl doplněn hostitelský Tk pohled; jeho animace ani grafické
indikátory nejsou měřením časování pinů Wokwi.

## Obnova událostí a legacy čas

Invalidace ruší rozpracované pulzy i čekající události, zachovává poslední platnou
`injector_ms`. Staré generace příkazů se zahodí. Hardware status vyvolá invalidaci
při přírůstku `dropped_tx`, ne opakovaně kvůli jednou vzniklé ztrátě. Události více
než 2 s před hostitelským časem jsou odmítnuty (`future_events_rejected`).

Legacy Mega parsuje absolutní mikrosekundy přes `strtoul`, nikoli AVR `double`.
Každý hostitelský stav obnoví časovou kotvu a z dvojice stavů odhadne poměr temp;
první stav použije `simulation_speed`. Změna epochy/reconnect či návrat hostitelského
času zruší otevřené pulzy. Naměřená MCU šířka pulzu zůstává oddělená od mapovaného
času konce. Tento odhad obsahuje přenosový jitter a není přesná synchronizace pinů.
Legacy 32bitové hostitelské mikrosekundy mají rozsah přibližně 71,6 minuty;
poté je nutný restart relace. Hardwarový chip používá 64bitové časy.
32bitové CKP/CMP čítače měněné ISR kopíruje Mega v `ATOMIC_BLOCK`.

Hostitelské hrany se standardně nevytvářejí. Pro jejich skutečný záznam použijte
`--signal-events /tmp/edges.jsonl` (`Engine(..., collect_events=True)` v API).
Fronta zůstává omezená na 4096; při vysokých RPM musí odběratel číst dostatečně často.
Například při 6000 RPM a `--rate 2` se přes 5800 hran do jednoho odběru nevejde.
`dropped_events` zde znamená ztrátu volitelného hostitelského záznamu, nikoli ztrátu
pinů Wokwi. Vzor zubů i úhlové vzorky GUI jsou připravené při konstrukci generátoru.

## Pedál a výpočet paliva

Společná ECU aktualizuje `update_control(now)` každých 10000 µs virtuálního času.
Mock předává vstup pedálu přímo, firmware vzorkuje ADC každých 10 ms. Dávka se
promítne do fyzikálního modelu až jako dokončený vstřik. Změna požadavku nemění
již otevřený pulz. Nulovou dávku oznamuje výukový řadič dvojicí hran bez čekání;
v Mock mají shodný čas, na MCU může vzniknout velmi krátký pulz kvůli provádění
instrukcí. Nejde o fyzikální model pohybu ventilu. Platí předchozí pravidlo držení
poslední dávky při ztrátě komunikace. Regulace otáček zatím není
implementovaná: `requested_rpm=-1` znamená přímé řízení paliva podle pedálu.
