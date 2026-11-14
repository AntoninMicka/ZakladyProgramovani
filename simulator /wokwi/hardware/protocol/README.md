# Protokol a transportní hranice

## Hostitelský UART

Profil `--wokwi-hardware` používá existující JSON Lines obálku v1:
`version`, `type`, `sequence`, `simulation_time_us`, `source`, `data`, `error`.
`source=host` pro příjem a `source=engine-interface` pro odpovědi chipu.
Povinná integrita je navíc posledním polem objektu:

```json
"integrity":{"crc32":"01234567"}
```

CRC32 (IEEE) se počítá nad všemi přesnými bajty objektu **bez pole integrity**,
včetně poslední složené závorky, bez LF. Pole integrity se pak přidá těsně před
poslední závorku jako `,"integrity":{"crc32":"xxxxxxxx"}`. Počítá se tedy i verze,
sekvence, čas a zdroj, nejen fyzikální hodnoty. Je to kontrola poškození rámce,
ne autentizace. Python `encode(..., integrity=True)` i C `json_protect()` mají
vzájemné integrační testy. Maximální rámec je 16384 bajtů včetně LF; buffer je pevný.
Neúplný/příliš dlouhý řádek se zahodí po LF. C parser omezuje tokeny i hloubku vnoření,
kontroluje rozsahy, pořadí a čas. Bez platného CRC se stav nepoužije.

Příklad vytvoření skutečně platného rámce (checksum se nevypisuje ručně):

```python
from protocol import message, encode
packet = message('engine_state', 125, 1250000, {
    'rpm': 1500, 'crank_angle_deg': 270, 'cycle_angle_deg': 630,
    'map_kpa': 45, 'tps': .2, 'lambda_value': 1.02, 'iat_c': 25, 'clt_c': 85,
    'hardware': {'session': 42, 'mode': 'buffered', 'lookahead_us': 100000},
})
wire = encode(packet, integrity=True)
```

Příklady ze zadání bez `source/error` je třeba doplnit podle stávajícího protokolu
Pythonu. Adaptér přijímá `tps_percent` (0–100) jako alternativu `tps` (0–1) a `lambda`
jako alternativu `lambda_value`. Úhlový stav vyžaduje `cycle_angle_deg` v 0–720°.
RPM jsou 0–20000, MAP 0–300 kPa, IAT/CLT −100 až 250 °C, lambda 0.1–5.
Čítače a mikrosekundové časové značky jsou nezáporná celá čísla, v JSON do 2^53−1.

## Buffered relace

`hardware.session` je 32bitový identifikátor hostitelského spojení. Nová relace
uzavře rozpracované pulzy jako chybné a vymaže buffer; neobnovuje staré ECU povely.
V rámci relace musí růst sekvence i simulační čas stavů. Host při pause neposílá
opakovaně tentýž čas jako nový segment. První rámec ukotví mapování:

- `local_first_apply = first_receive_time + lookahead_us`
- `apply(t) = local_first_apply + t − first_host_time`
- `host_event_time = first_host_time + local_event_time − local_first_apply`

Události před ukotvením jsou explicitně chybné. Stejný offset platí po celou relaci,
aby se délka pulzu neměnila příchodem dalšího rámce. Nové RPM nevracejí historii;
pozdní aktualizace se odmítne, fázová odchylka se hlásí. Nejvýše 64 stavů, do 2 s dopředu.

`hardware_reset` s řádnou obálkou, CRC a `data.hardware` provede explicitní reset
adaptéru bez přehrání stavu. V běžném provozu host zakládá novou relaci při reconnectu.
Restart hostitele i chipu se loguje odděleně od fyzikálního času. Host rozpoznává
pokles sekvence chipu a zruší rozpracované ECU výstupy. Po ztrátě událostí nebo při
hlášení aborted/timeout se zruší také nejistá fronta hostitelského modelu.

## Výstupy

- `clock_sync`: `echo_sequence`, `ecu_time_us` (zde globální virtuální čas chipu),
  `hardware_session`. Python měří wall RTT a pozorovaný rozdíl časových os.
- `hardware_status`: běh, hloubka bufferu, fázová chyba, přijaté/neplatné zprávy,
  CRC chyby, staré/pozdní aktualizace, přetečení, ztracené TX rámce, pulzní chyby,
  watchdog a počet resetů. Publikuje se z odděleného service timeru.
- `ecu_event`: `signal=injector/ignition`, `action=start/end` nebo `charge/spark`,
  číselný `channel` 0–3 kompatibilní s Pythonem, čitelný `channel_name=INJ1..4/IGN1..4`,
  mapovaný `simulation_time_us`, původní `ecu_time_us`, `duration_us`, úhel kliky
  a cyklu při zachycení, relace. Jiskra je konec nabíjení, nikoli obě hrany současně.

Nepárový konec, opakovaný začátek, timeout a reset vytvoří chybový `ecu_event`
s `action=invalid/timeout/aborted` a neprázdným `error`. Nejde o platný dokončený
palivový impulz. Výchozí maximální délka rozpracovaného pulzu je 50 ms.
Polarity jsou z konfigurace; chyby se nezaměňují s běžným fyzickým přechodem.

TX fronta má 127 použitelných položek po nejvýše 1024 bajtech. Při plné frontě se
záznam explicitně započte jako ztracený; callback GPIO nečeká na UART. Oddělený
service timer odesílá již vytvořené rámce, dokončení UART uvolní položku.
1 Mbaud znamená přibližně 100 kB/s UART payloadu: při vyšších RPM může JSON událostí
překročit kapacitu. Začněte na 1000 RPM a sledujte ztráty; přesný provozní rozsah
musí stanovit měření. Binární reprezentace vysokofrekvenčních událostí je budoucí
backend, není zde označena za implementovanou. Modulární core ani ECU se kvůli ní
nemusí měnit.

## Oddělená diagnostika

Produkční firmware nikdy nečte tento protokol. Jeho UART TX vede pouze na `DIAG_RX`
chipu, který řádky s prefixem `ECU_DIAG` předává do Chips Console. Samotný firmware
vypisuje reset, GPIO RPM, synchronizaci, zub, cyklus, počty CKP/CMP a ADC hodnoty.
Přerušení a hardwarový timer neprovádějí Serial.print; diagnostika se tvoří v loop.

## Ověření a alternativa při nepoužitelnosti přímého UART

Wokwi dokumentuje [UART chipu](https://docs.wokwi.com/chips-api/uart),
[virtuální časovače](https://docs.wokwi.com/chips-api/time),
[explicitní piny Serial Monitoru](https://docs.wokwi.com/guides/serial-monitor)
a [RFC2217](https://docs.wokwi.com/vscode/project-config).
Jejich složení se musí ověřit skutečným prototypem. Nativní parser test to nenahrazuje.
Přímý socket ani síťové API uvnitř chipu nepředpokládáme.

Pokud runtime neumožní požadovanou topologii, podporované rozhraní k dalšímu ověření
je [Wokwi Simulation API](https://wokwi.github.io/wokwi-python-client/reference/wokwi_client/):
serial input/output a řízení simulace jsou vystavené pro externí klienty. Vyžaduje
vlastní dostupnost služby/oprávnění a nový integrační test; není to hotový backend.
Alternativně dva oddělené simulační procesy se samostatným komunikačním MCU mohou
sdílet externí transport, ale [nelze je ve Wokwi propojit dráty](https://docs.wokwi.com/faq)
a nelze tvrdit shodu jejich hodin. V takovém případě je nutná doložená cesta do chipu
v ECU simulaci, ne pouhý druhý síťový MCU. Produkční ECU se kvůli tomu nemění.
`step-controlled` zůstává nepodporovaný až do funkčního testu konkrétního API.
