# Výukový kontrolér kvadrokoptéry ve Wokwi

Samostatný projekt pro **Arduino Uno / ATmega328P**, který ukazuje čtení IMU,
odhad náklonu, regulaci a směšování čtyř motorových výstupů v konfiguraci X.
Komentovaný program je v `src/main.cpp`, výpočty v `src/controller.h`.

**Jde o výukovou simulaci elektroniky, nikoli o firmware pro skutečný let.**
Wokwi zde nemodeluje tah vrtulí ani pohyb dronu. Čtyři serva jsou pouze
viditelné ukazatele signálu pro ESC; polohu senzoru výstupy zpětně neovlivňují.
Není zde přijímač RC, rádiové spojení, držení výšky ani GPS.

## Periferie a zapojení

| Periferie | Zapojení na Uno | Úloha |
| --- | --- | --- |
| MPU6050 | SDA A4, SCL A5, AD0 GND, VCC 5 V, GND | Akcelerometr a gyroskop, I2C adresa 0x68 |
| Joystick | HORZ A0, VERT A1, VCC 5 V, GND | Požadovaný roll/pitch ±20°, středová mrtvá zóna |
| Potenciometr | SIG A2, VCC 5 V, GND | Plyn 0–1023 |
| Přepínač ARM | prostřední pin 2 na D2, pin 3 na GND | Vlevo DISARM, vpravo ARM, interní pull-up |
| Bzučák | kladný pin na D4, druhý na GND | Potvrzení a odmítnutí ARM |
| Vestavěná LED L | D13 | Svítí při ARM |
| M1 – přední levý, CCW | signál D5 | Ukazatel ESC |
| M2 – přední pravý, CW | signál D6 | Ukazatel ESC |
| M3 – zadní pravý, CCW | signál D9 | Ukazatel ESC |
| M4 – zadní levý, CW | signál D10 | Ukazatel ESC |

Serva mají v simulaci napájení V+ z 5 V a společnou zem. Tato náhrada není
napájecí schéma reálné kvadrokoptéry: ta potřebuje čtyři vhodné ESC, motory,
vrtule, baterii, rozvod výkonu a regulované napájení řídicí elektroniky.
Samotný čip MPU6050 vyžaduje správné napájení a úrovně I2C podle použitého modulu.

```text
                 PŘEDEK
       M1 (CCW)           M2 (CW)
                  IMU
       M4 (CW)            M3 (CCW)
```

## Lokální spuštění ve VSCodiu / VS Code

1. Otevři přímo složku `quadroptera_wokwi`.
2. Použij rozšíření Wokwi Simulator a PlatformIO IDE (doporučení v `.vscode`).
3. Pokud je potřeba, aktivuj licenci přes **F1 → Wokwi: Request a new License**.
4. Spusť **PlatformIO → Project Tasks → uno → General → Build**.
5. Spusť **F1 → Wokwi: Start Simulator**.
6. Počkej přibližně sekundu na kalibraci gyroskopu. MPU6050 nech v klidu
   s výchozími hodnotami: zrychlení X=0, Y=0, Z=1 g a všechny rotace 0 °/s.
7. Nech plyn na nule a joystick uprostřed. Přepni ARM zleva doprava.
   LED L se rozsvítí a monitor vypíše `ARM: vystupy aktivni.`
8. Pomalu zvyš plyn. Všechny čtyři ukazatele se při vodorovné IMU pohybují stejně.
9. Pohni joystickem a sleduj rozdíly mezi levými/pravými nebo předními/zadními motory.
10. Přepni zpět na DISARM: všechny výstupy se nastaví na 1000 µs.

Sestavení v terminálu PlatformIO z této složky:

```bash
pio run -e uno
```

Na Linuxu lze při standardní instalaci použít také
`"$HOME/.platformio/penv/bin/pio" run -e uno`.
Z kořene repozitáře použij `pio run -d quadroptera_wokwi -e uno` a ve Wokwi
vyber konfiguraci přes **Wokwi: Select Config File**.
Po úpravě programu zopakuj Build a restartuj simulaci.

Pokud Wokwi hlásí `firmware binary .pio/build/uno/firmware.hex not found in workspace`:

1. Spusť výše uvedené sestavení a počkej na `SUCCESS`. Wokwi program sám nepřekládá.
2. Přes **F1 → Wokwi: Select Config File** vyber `quadroptera_wokwi/wokwi.toml`
   (v této složce jde přímo o `wokwi.toml`). Cesty k firmwaru se vztahují k tomuto souboru.
3. Znovu spusť **Wokwi: Start Simulator**. Pokud chyba přetrvává, otevři přes
   **File → Open Folder** přímo složku `quadroptera_wokwi` a zopakuj spuštění.

`wokwi.toml` odkazuje na `.pio/build/uno/firmware.hex` a `firmware.elf`.
Používají se pouze knihovny Arduino a Wire dodané s platformou; další knihovny
nemusíš přidávat. Sériový monitor je nastaven na **115200 baud**.
Vypisuje stav, plyn, náklon a délky impulzů M1–M4 v mikrosekundách.
Sériový vstup v tomto projektu neslouží k řízení; používej periferie ve schématu.

## Webová varianta

Vytvoř nový Arduino Uno projekt na https://wokwi.com/projects/new/arduino-uno.
Do `sketch.ino` vlož obsah `src/main.cpp`. Vedle něj přidej záložku `controller.h`
s obsahem `src/controller.h` a nahraď `diagram.json` zdejším schématem.
Pak spusť simulaci a pokračuj od kalibrace výše.

## Jak regulace funguje

- IMU: rozsah akcelerometru ±2 g, gyroskopu ±250 °/s, čtení přes I2C přibližně 100 Hz.
- Komplementární filtr kombinuje integraci gyroskopu s náklonem z akcelerometru.
- PD regulátor roll/pitch používá chybu úhlu a tlumení z gyroskopu. Nemá integrátor.
- Yaw pouze tlumí otáčení podle gyroskopu; bez magnetometru nedrží absolutní směr.
- Mixer X rozděluje korekce na čtyři motory a posune společný základ při saturaci.
- Timer1 generuje čtyři sekvenční impulzy v rámci 20 ms (50 Hz), nezávisle na
  hlavní smyčce. 1000 µs znamená STOP, pracovní rozsah je 1100–2000 µs.
  Úhel serva je pouze vizualizace: sleduj i hodnoty v monitoru.

Osy jsou pro příklad definované: kladný roll = pravá strana dolů,
kladný pitch = předek nahoru, kladný yaw = zatáčení doprava.
Kladná korekce roll zvýší levé motory, kladná korekce pitch přední motory.
Konstanty regulace jsou demonstrační a nejsou odladěné pro fyzický stroj.

ARM je povolen jen po novém přepnutí při plynu ≤20, malém náklonu (<15°)
a joysticku uprostřed. Odmítnutý pokus vyžaduje nové DISARM → ARM.
Nulový plyn zastaví výstupy i při ARM. Chyba I2C, perioda přes 50 ms nebo
náklon nad 60° způsobí zastavení a vyžádá nové přepnutí ARM.
Při selhání inicializace IMU oprav zapojení a restartuj simulaci.
Příklad nemá nezávislý hardwarový watchdog: při úplném zamrznutí hlavní smyčky
může Timer1 dál vysílat poslední hodnoty. Jde o další důvod, proč jej nepoužít k letu.

## Pokusy

1. Zkus ARM se zvýšeným plynem: musí být odmítnut.
2. S vodorovnou IMU a středovým joystickem porovnej všechny čtyři výstupy.
3. Při přiměřeném plynu pohni joystickem doprava: zvýší se levá dvojice M1/M4.
4. U MPU6050 změň ovládacími prvky zrychlení např. na X=0, Y=0.5, Z=0.866 g.
   To napodobí statický náklon roll přibližně +30°. Regulátor jej kompenzuje
   zvýšením pravých motorů. Po změně vyčkej na ustálení filtru.
5. Změň rotaci Z na 20 °/s až po kalibraci. Výstupy CCW a CW se rozliší kvůli
   tlumení yaw. Rotace ve Wokwi znamená úhlovou rychlost, ne nastavený úhel.
6. Ověř DISARM a nulový plyn. Při resetu se vždy začíná ve stavu DISARM.

## Ověření výpočtů

Z této složky můžeš spustit testy na běžném počítači s překladačem G++:

```bash
g++ -std=c++11 -Wall -Wextra -Wpedantic -Werror tests/controller_test.cpp -o /tmp/quad_test
/tmp/quad_test
```

Testují mrtvou zónu joysticku, podmínky ARM, zastavení při nulovém plynu,
směry korekcí a saturaci mixeru. Neověřují běh I2C ani časování impulzů v simulátoru.

## Dokumentace

- [MPU6050 ve Wokwi](https://docs.wokwi.com/parts/wokwi-mpu6050)
- [Mapa registrů MPU6050 od výrobce](https://invensense.tdk.com/wp-content/uploads/2015/02/MPU-6000-Register-Map1.pdf)
- [Joystick](https://docs.wokwi.com/parts/wokwi-analog-joystick)
- [Serva jako ukazatele](https://docs.wokwi.com/parts/wokwi-servo)
- [Přepínač](https://docs.wokwi.com/parts/wokwi-slide-switch)
- [Lokální Wokwi a PlatformIO](https://docs.wokwi.com/vscode/platformio)
