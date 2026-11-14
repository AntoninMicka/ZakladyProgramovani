# Editor ECU a opravy revize

Ověření 14. 11. 2026. Záložka Editor ECU umožňuje psát C/C++ za běhu, uložit soubor,
přeložit jej a explicitně použít novou verzi. Použití znamená restart procesu
Wokwi a modelu od nuly. Nová relace zneplatní staré pulzy. Selhání překladu starý
proces nezastaví; selhání nového spuštění ponechá model pozastavený v Mock.
Editor kontroluje změny na disku a hash vstupů/artefaktů. Zobrazená předaná revize
je evidence spuštěného artefaktu a potvrzení komunikace, nikoli kryptografické
potvrzení kódu vykonávaného MCU.

## Propustnost hardware UART

Hardware používá 2 000 000 baud, 8N1: teoreticky 200 000 B/s v každém směru.
Chip balí až 16 hran do jedné JSON/CRC obálky; neúplnou dávku uzavře po 4 ms.
Dokončení UART ihned pokračuje dalším rámcem, takže přenos není omezen jedním
rámcem na 1ms service tick. Status zůstává po 100 ms. Fronta má 127 použitelných
položek po 2048 B. Nejde o neomezenou frontu ani neomezené otáčky.

Nativní test `wokwi/hardware/tests/throughput_test.c` používá skutečný C serializér,
10 bitů/bajt a model obsazení linky. Generuje čtyři hrany na válec za 720°, čtyři
válce, statusy a odpovědi na chráněné hostitelské zprávy při 20 Hz. Každý scénář
trvá 10 virtuálních sekund, značky mají 13 číslic, úhel je 719,999°.

| RPM | Hran/s | Rámců/s | B/s chip → host | Využití UART | Nejvyšší TX fronta | Ztráty |
| --- | --- | --- | --- | --- | --- | --- |
| 2000 | 267 | 280 | 74 257 | 37,1 % | 3 | 0 |
| 7500 | 1000 | 280 | 109 813 | 54,9 % | 3 | 0 |

Test požaduje využití pod 80 % a frontu kratší než 8. Toto stanovuje nativně
ověřený rozpočet pro výchozí čtyřválec do 7500 RPM při 20 Hz, nikoli naměřenou
propustnost Wokwi. Při vyšším `--rate`, delších číslech nebo dalších chybových
událostech je nutný nový rozpočet. Sledujte `dropped_tx`, `hardware_sequence_gaps`,
`dropped_frames`, pozdní události a skutečné VCD. Transport před blokujícím čtením
vyprázdní celou omezenou odchozí frontu (4 položky), nikoli jediný rámec.

## Model a čas

- Invalidace zruší otevřené pulzy a budoucí události; poslední platnou dávku drží.
  Kumulativní `dropped_tx` se porovnává s předchozím statusem.
- Wall zpoždění přes 250 ms obnoví deadline; model neprovádí neomezené dohánění.
- Značky více než 2 s v budoucnosti se odmítnou a započtou.
- Legacy Mega parsuje mikrosekundy celočíselně, průběžně obnovuje kotvu hodin,
  reaguje na změnu epochy a uchovává skutečnou šířku pulzu v doméně MCU.
  Jeho 32bitový čas je omezen přibližně na 71,6 minuty; nejde o přesnou synchronizaci.
- CKP/CMP čítače Mega se kopírují atomicky proti ISR.
- Legacy geometrii generuje `wokwi/configure_legacy.py` ze stejného JSON jako Python;
  VCD checker přijímá `--config` i pro hardwarový profil. Test pokrývá také 36-1
  a dvě nestejně vzdálené CMP polohy.
- Výchozí model má plyn 0,35 a nezhasne kvůli původní kombinaci výchozích hodnot.
  `{"rpm": null}` vypne stolici. `Supervisor.restart()` obnoví počáteční CLI povely.
- Hrany hostitele se generují jen pro přihlášený záznam (`--signal-events`).
  Vzor zubů a úhlové vzorky GUI jsou připravené jednou.
- Telemetrie sdílí serializér s `allow_nan=False`, všechny bridge mají `diagnostics()`.
  C CRC ověřuje rámec průběžně bez 16KiB zásobníkové kopie.

## Sestavení a formátování

Adresář `simulator ` byl přejmenován na `simulator`. Aktivujte prostředí z nové
cesty; starý shell může mít starou absolutní cestu v PATH. Soubory pyc, indexy clangd
a strojově závislý compile_commands.json byly odstraněny a ignorují se.
Jedna společná kopie `wokwi/wokwi-api.h` je v hardware adresáři dostupná symlinkem.
Binární WASM zůstávají verzované pro otevření Wokwi; po změně C je vždy přeložte:

```bash
# Z adresáře simulator:
python wokwi/hardware/scripts/build.py
# Legacy Mega + legacy chip:
pio run -d wokwi
python wokwi/configure_legacy.py --check
(cd wokwi && wokwi-cli chip compile engine-signals.chip.c -o engine-signals.chip.wasm)
# Pouze kontrola generovaných hardware souborů:
python wokwi/hardware/scripts/configure.py --check
```

ESP32 platforma je připnutá na `espressif32@6.9.0` (Arduino ESP32 2.0.17), která
podporuje použité timer API 2.x. AVR je připnuté na `atmelavr@5.1.0`.
WASM sestavené Wokwi CLI 0.29.1 / WASI SDK 25. Firmware sestavený pro ESP32,
legacy Mega i hardware Mega. Sdílená SDK hlavička a generované hlavičky se neformátují:

```bash
python -m pip install -r requirements-dev.txt
ruff format .
# Ručně psané C/C++: clang-format -i cesta/k/souboru.cpp
```

Lokálně prošlo 55 testů aplikace včetně pěti Tk testů a skutečného loopback RFC2217,
15 testů hardware Python/C/C++ a samostatný hostitelský test legacy chipu.
Tk test aplikuje změnu s testovacím CLI, kontroluje nový PID/revizi i zachování
starého procesu při chybě překladu. Žádný z těchto důkazů nenahrazuje skutečný běh
ESP32/AVR a virtuálních pinů ve Wokwi; ten zůstává otevřený dle
[akceptace](acceptance.md) a [hardware evidence](../wokwi/hardware/VERIFICATION.md).

## Navazující sjednocení Mock ECU

Mock nyní vykonává stejný `ecu_controller.h` jako firmware, přes nativní C++ adaptér.
Podrobnosti, závislosti a použití editoru pro Mock popisuje hlavní README.
Aktuální sada aplikace má 61 testů (včetně šesti Tk testů), hardware sada 15.
Původní Python regulace dávky v Mock byla odstraněna; společná demo ECU má pevnou dávku.
