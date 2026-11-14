# Výukový řadič kvadrokoptéry

Arduino Uno čte MPU6050, odhaduje náklon, porovnává jej s požadavkem joysticku
a směšuje čtyři motorové výstupy. Čtyři serva ve schématu jsou ukazatele signálu
pro regulátory motorů; nevytvářejí tah ani pohyb simulovaného dronu.

## Soubory

`src/main.cpp` obsluhuje periferie, kalibraci a hlavní smyčku. `src/controller.h`
obsahuje výpočty a podmínky aktivace. Původní README podrobně vysvětluje zapojení,
filtr, regulační členy a význam jednotlivých výpisů.

## Spuštění a první pokus

Sestav firmware přes tlačítko spouštěče. Otevři projekt v editoru s rozšířením
Wokwi, vyber `wokwi.toml` a spusť simulaci. První sestavení vyžaduje PlatformIO
s AVR frameworkem. Rozšíření Wokwi potřebuje vlastní aktivaci.

1. Nech IMU v klidu a přibližně sekundu počkej na kalibraci gyroskopu.
2. Dej plyn na nulu, joystick doprostřed a přepínač nejdřív do DISARM.
3. Přepni do ARM. LED L a sériový monitor potvrdí aktivaci, pokud jsou splněné podmínky.
4. Pomalu přidej plyn. Při vodorovném senzoru se mají všechny čtyři ukazatele chovat stejně.
5. Pohni joystickem a sleduj, které dvojice výstupů přidají či uberou.
6. Přepni DISARM: výstupy se vrátí na zastavovací impulz.

## Co sledovat

Joystick zadává požadovaný náklon. Snímač poskytuje měřený náklon a úhlovou
rychlost. Filtr kombinuje informace akcelerometru a gyroskopu, regulátor počítá
opravu a směšovač ji rozděluje motorům konfigurace X.

Wokwi periferie můžeš měnit v grafickém schématu. Konzolová CLI akce je pouze
šestisekundový běh s výchozími vstupy; vyžaduje token a může čerpat CI kvótu.
Není náhradou pokusu s joystickem a ARM v editoru.

Výstupy zpětně neotáčejí modelem IMU. Tato úloha proto ověřuje elektroniku a
výpočty, ne schopnost skutečného dronu stabilně letět.
