# Technický prototyp a výsledky ověření

Ověření: 14. 11. 2026. **Wokwi část zatím není akceptovaná jako dokončená integrace.**
Dodány jsou zdroje, zapojení, firmware, konfigurace, nativní prototyp a opakovatelný
scénář. Skutečný Wokwi běh chybí kvůli `Missing WOKWI_CLI_TOKEN environment variable`.
Žádný zde uvedený hostitelský test nevykonává instrukce ESP32 ani Wokwi WASM runtime.

## Aktuální důkazy

| Kontrola | Výsledek | Co prokazuje |
| --- | --- | --- |
| Hardware testy Python/C/C++ | 17 testů prošlo | následující nativní scénáře |
| UART 2 Mbaud | nativně 2000/7500 RPM: 37,1/54,9 %, peak TX 3, žádné ztráty | délky skutečně serializovaných rámců, 10 bitů/bajt, 10 s na scénář |
| C core – 8 scénářů | prošlo | 60-2, 720° CMP, RPM změny, stop/restart, analog, pulzy, polarity/poruchy, omezení front |
| Buffered doručení | prošlo | stejné GPIO termíny při různě časném doručení stavu před apply time |
| C++ ECU + C hw_core | prošlo | GPIO CKP → RPM 1000; CMP → synchronizace; čtyři INJ a čtyři IGN; watchdog |
| Časování nativní ECU | prošlo | injekce 3000 µs, dwell 2000 µs s krokem 25 µs; úhel jiskry v toleranci 0.4° při 1000 RPM |
| Python bridge → C adapter → Python model | prošlo | chráněné zprávy, mapování časů, zpracování injekčního pulzu v modelu |
| Chybné zprávy a CRC | prošlo | vadný JSON, délka, rozsahy, změna sekvence/obsahu, stale/late, bounded fronta |
| Reset a výpadek | prošlo nativně | explicitní abort/timeout, změna relace, staré události, watchdog, výstupy ECU OFF |
| ESP32 firmware | build BIN/ELF prošel | sestavitelnost, nikoli skutečný běh |
| Mega profil | build HEX/ELF prošel | přenositelnost vrstvy GPIO/timeru; ne časová výkonnost AVR |
| Vstupní a výkonový blok | nativní testy hran CKP/CMP, 5 ADC cest, 8 driverů a POWER_EN prošly | funkční hranice kabeláže/driverů, bez elektrického modelu zátěží |
| Custom Chip | build WASM prošel | ABI a sestavitelnost všech čtyř C modulů |
| Wokwi lint | bez chyb | známé piny, součástky, topologie souboru |
| Runtime Wokwi | neproveden | chybí CLI token; žádný skutečný VCD ani MCU/ADC výsledek |

Lint verze 0.29.1 vypisuje informační hlášení `unsupported-part` pro typ
`board-esp32-devkit-c-v4` (označuje jej jako undocumented); nemá pinové ani jiné
chyby a vrací úspěch. Typ desky je přitom uveden v oficiálním
[seznamu typů diagramu](https://docs.wokwi.com/diagram-format).

Použité nástroje: Wokwi CLI 0.29.1, WASI SDK 25 (LLVM 19.1.5), host Clang 21,
PlatformIO Espressif32 6.9.0 / Arduino ESP32 2.0.17 / Xtensa GCC 8.4.0;
Atmel AVR 5.1.0 / Arduino AVR 5.2.0 / AVR GCC 7.3.0.
Build cache byla kopie existujících veřejných toolchain balíčků v `/tmp/ecu-pio-core`.

## GUI ovládání CLI

Záložka Wokwi nově spouští sestavení, scénář a živou smyčku a zobrazuje procesní
výpis. Na skutečném Tk displeji bylo ověřeno vyhledání instalovaného CLI 0.29.1
přes `--version`. Živý stdin/stdout transport, potvrzení relace, návrat do Mock,
zastavení potomků a maskování tokenu ověřují lokální testovací procesy.
GUI neprovádí automatické opakování Wokwi simulace. Toto není výsledek skutečného
ESP32/Custom Chip běhu a otevřené body níže zůstávají beze změny.

## Povinný technický prototyp před přijetím topologie

| Bod ze zadání | Dosaženo nyní | Co musí ověřit skutečný runtime |
| --- | --- | --- |
| 1. Custom Chip ve VS Code | WASM, config, lint | chip se načte a vypíše ENGINE_INTERFACE_READY |
| 2. CKP virtuální timer | stejný C core prošel | VCD 60-2 na virtuálním pinu |
| 3. Capture GPIO a čas | nativní pulzy/dwell prošly | INJ/IGN hrany MCU odpovídají zachyceným značkám |
| 4. Analogové výstupy | tabulky/NTC/změna hodnot prošly | ADC MCU reaguje na dvě úrovně podnětu |
| 5. Chip ↔ MCU | nativní decoder/outputs prošly | skutečné CKP/CMP/ADC a výstupy ve Wokwi |
| 6. MCU/host transport | původní RFC test pouze proti loopback serveru | nová přímá UART topologie přes RFC2217 |
| 7. Bez protokolu v ECU | ověřeno ve zdroji a buildu | explicitní Serial Monitor ↔ chip s nezměněným ECU firmware |
| 8. Externí řízení času | není implementované | případný nový API backend; step-controlled se nepovažuje za podporovaný |
| 9. Pause Wokwi | nelze odvodit z host testů | změřit chování hodin, fronty a obnovy při skrytí/pause panelu |
| 10. Latence | nativní deadline invariance prošla | skutečné RTT, pozdní aktualizace, jitter a VCD |

## Opakování dostupných kontrol

Z adresáře `simulator`:

```bash
python wokwi/hardware/scripts/configure.py --check
PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -s wokwi/hardware/tests -v
# Původní Python/GUI/TCP sada na dostupném displeji a loopback socketu:
ECU_TEST_GUI=1 ECU_TEST_TCP=1 PYTHONDONTWRITEBYTECODE=1 \
  python -m unittest discover -s tests -v
python wokwi/hardware/scripts/build.py
```

## 1. Samostatný UART/GPIO prototyp ve Wokwi

Použijte běžné oprávnění Wokwi rozšíření nebo vlastní CLI token nastavený v prostředí;
token neukládejte do zdrojů. Před testem sestavte firmware a WASM.

```bash
# Z adresáře simulator:
python wokwi/hardware/scripts/make_scenario.py
cd wokwi/hardware
wokwi-cli . --scenario tests/prototype.yaml --timeout 6000 \
  --serial-log-file /tmp/ecu-prototype.jsonl --vcd-file /tmp/ecu-prototype.vcd
```

Scénář posílá chráněné stavy s 1000 RPM, ve druhé části mění analogové snímače,
čeká na skutečnou zachycenou jiskru a po skončení vstupu požaduje neaktivní CKP/CMP.
Je to generovaný testovací podnět bez Python fyziky, nikoli regulační smyčka.
Případný čas potřebný pro zápis UART scénářem musí být změřen; při zpoždění ověřte
`late_updates`, neprodlužujte tolerance tak, aby maskovaly nesprávné hodiny.

Přijetí prototypu vyžaduje:

1. `clock_sync` potvrzuje stejné sekvence a všechny JSON rámce projdou `protocol.decode`.
2. `hardware_status.received` roste, CRC/late/drop čítače jsou pro zdravou cestu nula.
3. Firmware v Chips Console hlásí `RPM≈1000`, `SYNC=1`, měnící se cyklus a ADC.
4. INJ1/IGN1 ve VCD odpovídají zachyceným `duration_us` i `ecu_time_us`.
5. Žádný simulační rámec není zpracován MCU a jeho boot/diagnostika nekazí transport.

Počáteční a konečný úsek rozběhu/zastavení oddělte od ustáleného VCD. Pro ustálený
úsek 1000 RPM (výchozí aktivní HIGH, CMP 0–12°) použijte z `simulator`:

```bash
python tools/check_vcd.py /tmp/ecu-steady-1000.vcd --rpm 1000
```

Požadovat 58 náběhů mezi trojnásobnými mezerami, CMP 720°, odpovídající šířky,
a kompletní INJ/IGN pulzy. Kontrolor nenahrazuje samostatné posouzení změn RPM,
polarity/poruch ani porovnání fyzické hrany s rámcem události.

## 2. Skutečná vazba model → snímače → ECU → výstupy → model

Spusťte `hardware/wokwi.toml` ve VS Code a hostitele:

```bash
python wokwi/hardware/scripts/run_host.py --duration 30 \
  --telemetry /tmp/ecu-hardware.jsonl --console-telemetry
```

Nepoužívat `--rpm`: držení pevných otáček by zakrylo vliv ECU na model.
Demonstrační ECU zde používá pevnou dávku a předstih. Sledujte změnu RPM/lambda po
zachycených pulzech a po změně zatížení. Pro další srovnání lze změnit dávku v
konfiguraci, znovu sestavit a porovnat s uloženou telemetrií za stejného počátečního
stavu. Do akceptace uložit konfiguraci, verze, log, VCD a jejich časové epochy.

Proveďte také nižší/vyšší RPM ve stolici, poruchu zubu a CMP, neplatný CRC,
přerušení Pythonu, restart MCU/simulace, pause/obnovu Wokwi a opožděné stavy.
Ověřit omezené fronty, explicitní chybné pulzy, neaktivní výstupy po ztrátě CKP
a nové ukotvení epoch po restartu. Výstup `link=True` není důkaz této vazby.

## Přesnost a známé meze

Dosud nebyly naměřeny skutečná latence Wokwi, GPIO jitter, odchylka ADC ani drift
host/chip hodin. Nativní 1µs plánování a 25µs timer ECU jsou návrhové parametry,
ne naměřená přesnost emulovaného MCU. Nekalibrované analogové tabulky a pevná dávka
ECU nejsou emulací skutečného automobilu. JSON TX může při vyšších RPM přetéct;
ztracená data se nesmí vydávat za úplný záznam. MCU časování AVR je zvlášť neověřené.

Pokud přímý UART prototyp neprojde, další implementaci topologie zastavit a vyhodnotit
oddělený backend z [protokolové dokumentace](protocol/README.md). Nevracet simulační
protokol do produkčního firmware a neoznačovat fázi za přijatou pouze na základě
výměny telemetrického JSON.

## Rozšířené schéma ECU

Diagram nyní odděluje vstupy snímačů, MCU, drivery a aktivitu osmi zátěží.
Přepínač hlavního relé hradluje aktivitu za drivery. VCD rozlišuje povel a zátěž.
Nové `sensor-front-end` a `output-stage` WASM sestavené CLI 0.29.1; lint bez chyb
či varování (zůstává informační `unsupported-part` pro desku ESP32).
17 hardware testů včetně nativního testu skutečných zdrojů obou chipů prošlo.
Logické bloky nejsou fyzikální simulací MOSFET, IGBT ani analogové ochrany vstupů.
Skutečný běh nového schématu v MCU/Wokwi zůstává otevřený.
