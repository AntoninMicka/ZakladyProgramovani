# Protokol ECU v1

Transport RFC2217 přenáší UTF-8 JSON Lines. Jeden objekt končí LF; maximum rámce
je 16384 bajtů včetně LF. Příliš dlouhý řádek se zahodí až po další LF.
Dekodér uchovává fragmenty mezi čteními a počítá neplatné rámce.
Demo firmware má menší vstupní buffer 2048 bajtů a čte pouze `engine_state`.

Každá zpráva má povinnou obálku:

```json
{"version":1,"type":"actuators","sequence":125,"simulation_time_us":1250000,"source":"ecu","data":{"injector_ms":3.2,"ignition_deg":15,"load_nm":12},"error":null}
```

`version` je přesně 1, `sequence` a `simulation_time_us` nezáporná celá čísla,
`source` neprázdný řetězec, `data` objekt. NaN/Infinity nejsou přípustné.
Sekvence je čítač odesílatele, nikoli potvrzování doručení. TCP zachovává pořadí
v jednom spojení; zprávy se při výpadku znovu nepřehrávají.
`error` je null nebo objekt například `{"code":"invalid_event","message":"..."}`.
Zpráva s chybou se nepoužije jako povel a chyba se zaloguje; nepodporované vstupy
zvyšují diagnostické čítače. Obecný bridge automaticky nepotvrzuje každý povel.

| type | Směr | data |
| --- | --- | --- |
| engine_state | host → ECU | snímek motoru a diagnostiky |
| actuators | ECU → host | injector_ms, ignition_deg, load_nm, throttle, idle, rpm |
| ecu_event | ECU → host | signal, action, channel, simulation_time_us |
| clock_sync | ECU → host | echo_sequence, ecu_time_us, volitelná diagnostika |
| signal_events | vyhrazeno pro budoucí transport | events: seznam datovaných hran |
| error | oběma směry | chybová obálka a popis v error |

`actuators` mění hodnoty v následujícím kroku, není to přesně datovaný povel.
`rpm` aktivuje stolici s pevnými otáčkami; návrat k volné dynamice provede restart.
Hodnoty: throttle/idle 0–1, injector_ms 0–100 ms, ignition_deg −180 až 180°,
load_nm 0–1000 Nm, rpm do nakonfigurovaného maxima. Neznámé klíče jsou odmítnuty.

Snímek obsahuje `rpm`, `map_kpa`, `tps` (0–1), `iat_c`, `clt_c`, `lambda_value`,
`crank_angle_deg` (0–360), `cycle_angle_deg` (0–720), `simulation_time_us`,
`signal_levels` (počáteční/aktuální CKP/CMP), diagnostiku a poslední délky impulzů.
Původní názvy `time_s`, `throttle`, `coolant_c`, `crank_deg` (historicky 720°)
zůstávají jako kompatibilní aliasy.

## Diskrétní výstupy ECU

```json
{"version":1,"type":"ecu_event","sequence":126,"simulation_time_us":1251000,"source":"ecu","data":{"signal":"injector","action":"start","channel":0,"simulation_time_us":1251000},"error":null}
```

Čas uvnitř `data` je závazný čas události v doméně hostitelské simulace;
čas obálky popisuje čas zprávy. Kanály jsou 0 až počet válců minus jedna.
Vstřikovač: `start` a `end`; rozdíl značek udává délku impulzu v µs.
Zapalování: `charge` a `spark`; rozdíl udává dwell. Záměrně se nezaměňuje
nabíjení cívky se samotnou jiskrou. Duplicitní začátek, nepárový konec,
záporný/obrácený čas a neplatný kanál jsou odmítnuty.

Budoucí události čekají v omezené prioritní frontě. Pevný makrokrok se podle nich
rozdělí na dílčí integrační úseky. Opožděná událost zachová původní značku pro
výpočet délky, ale fyzikálně se uplatní až teď; žádný rollback.
Po výpadku se zruší čekající události, otevřené pulzy a dávka paliva. Generace
povelů zabrání použití staré fronty po reconnectu. Nové povely se nezahodí.

## Lokální rozhraní chipu

MCU UART1 → chip RX, 1 Mbaud: `S rpm100 map100 tps100 iat100 clt100 lambda100\n`.
Číselné hodnoty jsou násobeny 100, bez desetinné tečky. MAP v kPa, teploty v °C,
TPS 0–1, lambda bez jednotky. Samostatné digitální hrany se po UART neposílají.

Chip TX → MCU UART1: `E wokwi_time_us kind channel level\n`.
`kind=0` je vstřikovač, `kind=1` cívka. Úroveň 1 znamená start/charge, 0 end/spark.
Chip má kruhovou frontu 63 záznamů a při přetečení vypíše `CAPTURE_OVERFLOW`.
MCU při první zachycené hraně ukotví čas Wokwi k odhadu hostitelského času.
Relativní délky se zachovají; absolutní zarovnání není garantováno.
32bitové časové značky demonstračního firmwaru přetečou asi za 71 minut:
pro delší běh je nutné rozšířit čítače a znovu provést integrační akceptaci.

Analogové výukové převody (oříznuté na 0–5 V): MAP/40,
TPS×5, (IAT+40)/33, (CLT+40)/33, (lambda−0.5)/0.3.
Nejde o elektrické charakteristiky skutečných snímačů.
