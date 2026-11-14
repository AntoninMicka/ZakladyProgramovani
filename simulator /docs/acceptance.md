# Evidence a akceptace druhé fáze

Ověření 14. 11. 2026: všech 31 Python testů včetně skutečného TCP testu, geometrie vizualizace
a dvou skutečných Tk GUI testů prošlo;
prošel také samostatný C host test. Implementace je připravena pro lokální SIL a pro integrační
ověření s Wokwi. Celá fáze **není zatím akceptována**, protože chybí skutečný běh
s demonstračním MCU a měření na virtuálních pinech.

| Oblast | Dosažené ověření | Stav |
| --- | --- | --- |
| Živá vizualizace | skutečný běh Tk okna, ovládání plynu/zátěže/pauzy/rychlosti a 16 válců | ověřeno lokálně |
| Model, virtuální hodiny, samostatné vlákno | Python testy + skutečný CLI Mock | ověřeno lokálně |
| Úhel, 60-2, CMP 720°, změny RPM | deterministické virtuální testy | ověřeno lokálně |
| Vstřikování, charge/spark, budoucí/pozdní události | automatické testy | ověřeno lokálně |
| Protokol a omezení front | automatické testy včetně vadných/dlouhých rámců | ověřeno lokálně |
| Obousměrný RFC2217, disconnect/reconnect | pySerial klient proti PortManager serveru přes skutečný loopback TCP | ověřeno bez Wokwi |
| Ukončení vláken, pause/restart | automatické testy | ověřeno lokálně |
| MCU firmware | PlatformIO Mega 2560, HEX/ELF | build prošel |
| Custom Chip | Wokwi CLI 0.29.1, WASM; C host test s náhradami API | build a host test prošly |
| Zapojení | `wokwi-cli lint .` | bez nálezů |
| Uzavřená smyčka s MCU ve Wokwi | pokus o CLI běh skončil `Missing WOKWI_CLI_TOKEN environment variable` | otevřené |
| Přesnost digitálních pinů Wokwi | připraven Logic Analyzer a kontrola VCD; dosud žádný skutečný VCD | otevřené |

Hostitelský C test testuje skutečný zdroj chipu: dvě otáčky 1000 RPM,
60-2 včetně trojnásobné mezery, CMP, změnu na 2000 RPM, zastavení, analog a zachycení
vstřikovací hrany v čase zdroje. Nenahrazuje běh ve Wokwi.
Kontrolor VCD má automatické testy na syntetických datech včetně zamítnutí plného
60zubého kola; syntetický záznam není důkaz virtuálních pinů.

## Opakování lokálních kontrol

Z adresáře `simulator `:

```bash
ECU_TEST_TCP=1 PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -s tests -v
clang -std=c11 -Wall -Wextra -Werror -Wno-unknown-attributes -Wno-unused-function \
  -I wokwi tests/chip_host_test.c -lm -o /tmp/ecu-chip-test
/tmp/ecu-chip-test
pio run -d wokwi
cd wokwi
wokwi-cli chip compile engine-signals.chip.c -o engine-signals.chip.wasm
wokwi-cli lint .
```

Použitý PlatformIO: Atmel AVR 5.1.0, Arduino AVR 5.2.0, GCC AVR 7.3.0.
Build využil kopii nainstalovaných balíčků v `/tmp/ecu-pio-core`, protože obvyklý
cache adresář byl pouze pro čtení. Sestavení samo neprokazuje běh firmware.

## Integrační postup s Wokwi

1. Sestavit HEX/ELF a WASM dle README a spustit `wokwi/wokwi.toml` v rozšíření
   Wokwi s viditelným panelem simulace. Alternativně použít Wokwi CLI s tokenem
   nastaveným mimo zdrojový kód. Token se do repozitáře neukládá.
2. Spustit Python `--mode wokwi --baudrate 1000000 --rpm 1000 --duration 30
   --telemetry /tmp/ecu-wokwi.jsonl`. Ověřit `link=True`, rostoucí received,
   nenulové délky injection/dwell a aktivitu vestavěné LED.
3. Pro ověření regulace vynechat `--rpm`, sledovat RPM a lambda při změně
   zatížení (`Supervisor.engine.command({'load_nm': ...})`). Test stolice
   s pevnými RPM není důkaz regulační smyčky dynamického modelu.
4. Zastavit Wokwi a po několika sekundách znovu spustit. Python musí pokračovat,
   přejít na link=False a následně True, zvýšit počet spojení a znovu přijímat
   párované impulzy. Zkontrolovat omezené fronty a chyby nepárových impulzů.
5. Z Logic Analyzeru exportovat skutečný VCD: D0 CKP, D1 CMP, D2 INJ0, D3 COIL0.
   Po ustálení 1000 RPM zachytit alespoň 0.5 s. Je-li v záznamu počáteční náběh
   od nuly nebo změna RPM, tento úsek oddělit, protože kontrola předpokládá
   konstantní otáčky. Jména kanálů lze přepsat přepínači.
6. Spustit `python tools/check_vcd.py /cesta/skutecny.vcd --rpm 1000`.
   Kontrola požaduje 58 náběhů mezi trojnásobnými mezerami, správnou CKP šířku,
   CMP periodu 720°/šířku 12° a úplné injektorové/coil impulzy. Výchozí tolerance
   intervalů je 30 µs; není to tvrzení o již dosažené přesnosti. Porovnat
   naměřené šířky s `last_injection_us` a `last_dwell_us` v hostitelské telemetrii.
7. Zopakovat při 1500 a 2000 RPM a při změně RPM. Dynamický průběh musí být
   posouzen vůči časům změn skutečně přijatým lokálním chipem, nikoli času doručení
   hostitelského TCP rámce. Porovnat CKP/CMP fázi, nikoli jen počty.
8. Uložit skutečnou konfiguraci, VCD, telemetrii, verze nástrojů a výsledky měření.
   Vyhodnotit RTT, pozdní události a změnu pozorovaného offsetu hodin samostatně
   od chyb lokálního GPIO časování. Teprve potom přijmout odpovídající body fáze C/D.

Použitá dokumentace: [RFC2217](https://docs.wokwi.com/vscode/project-config),
[čas Wokwi](https://docs.wokwi.com/chips-api/time),
[pin_watch](https://docs.wokwi.com/chips-api/gpio),
[Custom Chip WASM](https://docs.wokwi.com/guides/custom-chips-to-wasm).
