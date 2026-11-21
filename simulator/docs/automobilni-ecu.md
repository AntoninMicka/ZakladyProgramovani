# Automobilní ECU pro model auta

V režimu **Auto** a **Jízda po okruhu** s lokálním Mock backendem se nyní
aktivuje automobilní větev společné C++ ECU. Pedál APP zadává požadavek na
otevření klapky a moment, místo aby motor vždy držel pedálem zadané otáčky.
Volnoběh má vlastní PI regulaci a ochrany reagují na provozní podmínky.

Spuštění je stejné jako dosud:

```bash
# Z kořene repozitáře:
simulator/.venv/bin/python simulator/main.py --mode mock --gui --vehicle
simulator/.venv/bin/python simulator/main.py --mode mock --gui --drive --rate 60
```

Obě akce jsou také ve společném spouštěči. Nový kód se sestaví automaticky
podle obsahu C++ hlavičky; po úpravě ukonči starý běh a spusť jej znovu nebo
použij Editor ECU → Použít v simulaci.

## Způsob řízení

- **Pedál a klapka:** APP je vstup řidiče, TPS je skutečná poloha klapky.
  ECU zadává klapce cílovou polohu, model má odezvu s časovou konstantou 60 ms.
- **Vzduch a palivo:** MAF a otáčky určují dávku pro výukový poměr 14,7:1.
  MAP, IAT a barometrický tlak slouží jako kontrola a náhradní výpočet vzduchu.
- **Lambda:** v zahřátém ustáleném provozu upravuje pomalá korekce dávku
  v rozsahu 0,90–1,10. Nepracuje při dojezdu bez paliva ani řazení.
- **Volnoběh:** zahřátý cíl 850 ot/min, za studena až 1100. PI regulace má
  anti-windup a předřazení podle zátěže motoru/spojky. Cíl se používá jen
  pro volnoběh, nikoli jako globální rychlostní požadavek během jízdy.
- **Brzdění motorem:** při uvolněném pedálu, zařazeném převodu a rychlosti
  nad 7 km/h se nad 1400 ot/min palivo vypne. Obnoví se pod 1100 ot/min;
  hystereze brání rychlému přepínání. Řazení tuto funkci dočasně přeruší.
- **Brzda:** její sešlápnutí má přednost před současným plynem; při nízké
  rychlosti zůstává aktivní udržování volnoběhu.
- **Zastavení v D/R:** při sešlápnuté brzdě se přenos spojky omezí na 12 Nm,
  aby automobil mohl držet volnoběh i proti stojícím kolům. Jde o zjednodušený creep.
- **TCU a ESP:** během řazení se omezí klapka; požadavek omezení momentu ESP
  se provede přes vzduch. Model moment podruhé nenásobí stejným omezením.
- **Prokluz:** při nadměrné rychlosti předních kol proti zadním/vozidlu
  omezí ECU požadavek plynu. Neprovádí druhé nezávislé řízení ABS brzd.
- **Omezovač:** neutrál přibližně 4000 ot/min, zařazený převod 6500;
  opětovné zapnutí paliva je o 250 ot/min níž.
- **Napětí a tlak paliva:** doba otevření vstřikovače zahrnuje kompenzaci
  mrtvé doby a odmocninovou korekci tlaku. Model paliva používá stejné
  veličiny, takže kompenzace nezvyšuje moment jen prodloužením elektrického pulzu.
- **Zapalování:** předstih je v této mapě převážně 15°, při teplotní ochraně 8°;
  doba nabíjení cívky se přizpůsobuje napětí v rozsahu 1,5–3,5 ms.

## Jak se používají senzory

Do C++ ECU přechází pojmenovaný snímek 38 hodnot. Ne všechny veličiny mají
vstupovat přímo do množství paliva: některé určují ochrany, jiné věrohodnost
zpráv nebo požadavek jiné řídicí jednotky.

| Vstupy | Úloha |
| --- | --- |
| CKP/CMP | původní měření otáček, synchronizace válců a časování pulzů |
| APP | požadavek řidiče na moment/klapku |
| TPS | skutečná klapka a kontrola rozsahu; vizuálně odlišena od APP |
| MAF, MAP, IAT, barometr | základ dávky, hustota vzduchu a náhradní výpočet |
| Lambda | omezená korekce zahřáté směsi |
| Kapalina | studený volnoběh, obohacení a teplotní omezení |
| Olej – teplota/tlak | teplotní ochrana; nízký tlak po rozběhu ochranně vypne palivo |
| Napětí, tlak paliva | korekce vstřiku a dwell; příliš nízký tlak vypne palivo |
| Palivo v nádrži | při prázdné nádrži se vstřikování vypne |
| Teplota výfuku | omezení momentu a předstihu |
| Rychlost, převod, řazení | dojezd bez paliva, volnoběh, omezovač a omezení při řazení |
| Čtyři rychlosti kol | kontrola prokluzu přední poháněné nápravy |
| Brzda a čtyři tlaky brzd | přednost brzdy a kontrola věrohodnosti rozsahů |
| Úhel řízení, stáčení, podélné/příčné zrychlení | věrohodnost dat; vlastní zásah ESP řídí ABS/ESP jednotka |
| Vstupní/výstupní otáčky převodovky | kontrola věrohodnosti vůči CKP a rozsahům |
| ABS/ESP a momentový limit | požadavek nadřazené regulace a kontrola rozsahů |
| Přídavná zátěž a moment spojky | předřazení volnoběžného regulátoru |
| Počet válců | přepočet MAF na dávku jednotlivého pracovního cyklu |
| Platnost CAN | nouzové omezení při ztrátě zpráv podvozku |

Motorové senzory předává lokální hostitelský adaptér. Podvozkové požadavky,
kola, převod a zásahy pocházejí z doručených CAN rámců; přímý signál brzdového
pedálu zůstává dostupný i při výpadku komunikace. Zátěž a některé provozní
odhady jsou přímo z fyzikálního modelu, ne skutečné fyzické snímače.

## Diagnostika a ochrany

Stav ECU je v `bridge.controller` a v `state.vehicle.ecu`, v tabulce senzorů
GUI a na diagnostickém displeji kokpitu. Textová telemetrie ukazuje
`ECU_state`, `ECU_faults` a `trim`.

| Stav | Význam |
| --- | --- |
| 0 | jízda / momentový požadavek |
| 1 | udržování volnoběhu |
| 2 | brzdění motorem bez paliva |
| 3 | omezovač otáček |
| 4 | ochranné vypnutí paliva |
| 5 | nouzový režim při ztrátě podvozkových zpráv |

`car_faults` je bitová maska výukové diagnostiky (nikoli standardní OBD DTC):
1 = neplatný nebo starý snímek, 2 = CAN timeout, 4 = tlak oleje,
8 = teplotní ochrana, 16 = nízké napětí, 32 = náhrada MAF výpočtem MAP,
64 = omezení prokluzu, 128 = věrohodnost podvozkových dat,
256 = prázdná nádrž, 512 = nízký tlak paliva.

Vstupní snímek musí být konečný a nejvýše 300 ms starý. Bez validních
podvozkových zpráv je požadavek klapky omezen na 20 %. Ochrana oleje má
2sekundovou prodlevu po aktivaci a kontroluje se nad 1100 ot/min. Kapalina
od 105 °C omezuje moment, při 125 °C vypíná palivo. MAF mimo rozsah se nahrazuje
MAP výpočtem; nekonečná/NaN hodnota v předávaném snímku jej zneplatní celý.

## Co bylo upraveno ve fyzice

Jen v lokálním automobilním režimu má motor samostatnou klapku, plnicí tlak
12–100 kPa, zjednodušený průtok vzduchu, efektivní dávku po mrtvé době a tlaku
paliva a odvozenou lambdu. Průtok vstřikovače 8 g/s a zdvihový objem 0,5 l na
válec jsou výukové kalibrace. Vliv dávky na moment stále vychází ze zdejší
zjednodušené momentové mapy, doplněné omezením podle směsi. Spotřeba v nádrži
používá stejnou efektivní dávku a průtok jako lambda model.

Vzduch se integruje po skutečných událostech ECU, nikoli podruhé v predikci
CKP. Cíl klapky se do modelu přenese na následující makrokrok (obvykle 1 ms).
Nejde o model skutečného spalování, kalibraci konkrétního vozu ani firmware
použitelný k ovládání fyzického motoru.

## Studentský motor a Wokwi

Samostatný motor bez modelu auta dál používá původní studentskou
`update_control()`. Automobilní režim používá `update_vehicle_control()`
ve stejné hlavičce `wokwi/hardware/firmware/include/ecu_controller.h`.
Při úpravách automobilního regulátoru upravuj tuto druhou funkci.

Wokwi firmware novou funkci obsahuje, ale jeho současné zapojení nepředává
celý automobilní senzorový snímek ani servo klapky. Proto tam automobilní
režim automaticky nezapínáme: běží dosavadní větev řízení motoru. Plná
automobilní smyčka je ověřena v lokálním Mock, nikoli na MCU či Wokwi pinech.
Nativní překlad ověřuje C++ logiku. Sestavení firmware pro ESP32 i Mega
bylo také ověřeno; automobilní smyčka na Wokwi/MCU pinech ověřena nebyla.

## Ověření

```bash
cd simulator
.venv/bin/python -m unittest discover -s tests -p test_automotive_ecu.py -v
```

Testy používají skutečnou C++ ECU a její pulzy: volnoběh a změnu zátěže,
pedál/moment, soulad MAF/lambda, kompenzaci napětí a tlaku, studený volnoběh,
omezení lambda trimu, MAP fallback, brzdění motorem, omezovač, nouzový CAN,
přednost brzdy, jediný zásah ESP, starý snímek a ochranné vypnutí při závadách.
Samostatně bylo ověřeno i zabrzděné zastavení v D při volnoběhu, skutečná
šířka coil pulzů při nízkém napětí a předstih při vysoké teplotě výfuku.
Testovací řidič se stejnou C++ ECU objel platné kolo okruhu bez diagnostických
závad (77,590 s virtuálního času; nejde o ověření fyzického joypadu či GUI).
Pevná stolice RPM se používá jen v testech korekcí; volnoběh a jízda se
ověřují bez přímého držení otáček.
