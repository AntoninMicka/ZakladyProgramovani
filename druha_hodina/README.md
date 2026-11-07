# Druhá hodina: čtení sériové linky v simulátoru Wokwi

Projekt pro **Arduino Uno** ukazuje příjem jednotlivých znaků, sestavení řádku
a zpracování textového příkazu. Příkazy ovládají vestavěnou LED označenou **L**
(pin 13), takže nepotřebujeme další součástky ani knihovny.

## Webová varianta: spuštění v prohlížeči

1. Otevři [nový projekt Arduino Uno ve Wokwi](https://wokwi.com/projects/new/arduino-uno).
2. Obsah záložky `sketch.ino` nahraď obsahem zdejšího souboru `src/main.cpp`.
3. Obsah záložky `diagram.json` nahraď obsahem zdejšího souboru `diagram.json`.
4. Spusť simulaci zeleným tlačítkem ▶.
5. Do vstupu sériového monitoru pod simulací napiš `pomoc` a stiskni Enter.

Program nastavuje rychlost na **9600 baud**. Wokwi u Una připojí sériový monitor
automaticky a rychlost rozpozná. Nastavení `newline: "lf"` přidává po Enteru
znak `\n`, kterým program pozná konec příkazu.
Viz [dokumentace sériového monitoru Wokwi](https://docs.wokwi.com/guides/serial-monitor).

## Lokální varianta: Wokwi ve VS Code / VSCodium

Zdrojové soubory upravuješ a firmware sestavuješ na svém počítači.
Simulaci potom spouštíš v rozšíření Wokwi přímo v editoru; fyzické Arduino
ani připojení přes USB nepotřebuješ. První instalace nástrojů a aktivace licence
vyžadují připojení k internetu. Tato varianta neznamená nastavení offline režimu.

1. Otevři přímo složku `druha_hodina` přes **File → Open Folder**.
2. Nainstaluj rozšíření **Wokwi Simulator** (`wokwi.wokwi-vscode`)
   a **PlatformIO IDE** (`platformio.platformio-ide`). Jsou uvedena také
   v doporučeních rozšíření projektu. Dostupnost závisí na katalogu rozšíření
   používaném editorem.
3. Pokud ještě nemáš aktivovanou licenci, stiskni **F1 → Wokwi: Request a new License**
   a dokonči aktivaci v prohlížeči i editoru.
4. V PlatformIO zvol **Project Tasks → uno → General → Build**.
   Při prvním sestavení PlatformIO stáhne AVR nástroje a Arduino framework.
5. Přes F1 spusť **Wokwi: Start Simulator**.
6. Do sériového monitoru simulátoru napiš `pomoc` a stiskni Enter.
   Potom odešli `zapni`: vestavěná LED **L** se rozsvítí. Příkaz `stav` vypíše
   `LED sviti.` a `vypni` LED zhasne.

Alternativně v terminálu PlatformIO sestav firmware příkazem:

```bash
pio run -e uno
```

Pokud běžný terminál příkaz `pio` nezná, použij terminál PlatformIO.
Při standardní instalaci PlatformIO IDE na Linuxu lze ze složky `druha_hodina`
použít také plnou cestu k nástroji:

```bash
"$HOME/.platformio/penv/bin/pio" run -e uno
```

Úspěšné sestavení končí hlášením `[SUCCESS]` a vytvoří oba soubory firmwaru
uvedené níže. Teprve potom spusť simulátor.

`platformio.ini` sestavuje `src/main.cpp` pro Arduino Uno.
`wokwi.toml` odkazuje na vzniklé soubory `.pio/build/uno/firmware.hex`
a `.pio/build/uno/firmware.elf`. Wokwi potřebuje firmware nejprve sestavit;
po každé změně programu zopakuj Build a restartuj simulaci. Nepoužívej Upload,
ten slouží k nahrávání do fyzické desky. Složka `.pio/` se do Gitu neukládá.

Pokud máš v editoru otevřený celý repozitář, použij **Wokwi: Select Config File**
a vyber `druha_hodina/wokwi.toml`. Sestavení z kořene repozitáře lze provést
v terminálu s dostupným `pio` příkazem `pio run -d druha_hodina -e uno`.
Pokud se objeví chyba o chybějícím firmwaru, nejprve ověř úspěšný Build
a existenci obou výše uvedených souborů.

### Zdrojový soubor a IntelliSense

Program upravuj v `src/main.cpp`. Obsahuje `#include <Arduino.h>` a funkce
`setup()` a `loop()`, takže jej PlatformIO překládá přímo jako C++.
Soubor `.ino` už lokální projekt nepoužívá; tím odpadá varování IntelliSense
u nepodporované přípony i nutnost filtrovat převáděný soubor `.ino.cpp`.

Po přechodu ze starší verze zavři záložku `sketch.ino`, otevři `src/main.cpp`
a spusť **PlatformIO: Rebuild C/C++ Project Index**. Potom zopakuj **Build**.

Pokud se objeví „Nothing to build“, ověř, že existuje `src/main.cpp` a že
`platformio.ini` neobsahuje staré `src_dir = .` ani `build_src_filter`
zaměřený na `sketch.ino`. Projekt používá výchozí zdrojovou složku `src`.

Podklady: [Wokwi a PlatformIO](https://docs.wokwi.com/vscode/platformio),
[konfigurace wokwi.toml](https://docs.wokwi.com/vscode/project-config)
a [zprovoznění rozšíření](https://docs.wokwi.com/vscode/getting-started).

## Co vyzkoušet

Příkazy piš malými písmeny bez diakritiky, každý na samostatný řádek:

Po Enteru program automaticky vypíše přijatý řádek, například `Prijato: [zapni]`,
a potom výsledek příkazu. Prázdný řádek potvrdí jako `Prijato: []`.
Řádky delší než 64 bajtů odmítne chybovou zprávou.
Přijaté znaky navíc okamžitě vrací do monitoru ještě před Enterem, takže je
vidět, že příjem funguje. Pokud monitor sám zobrazuje zadávaný text, můžeš ho
vidět dvakrát. Příkaz odešli Enterem; podporované konce řádků jsou CR, LF i CRLF.

| Vstup | Očekávaný výsledek |
| --- | --- |
| `pomoc` | Vypíše seznam příkazů. |
| `zapni` | Rozsvítí vestavěnou LED a vypíše `LED zapnuta.` |
| `stav` | Vypíše `LED sviti.` |
| `vypni` | Zhasne LED a vypíše `LED vypnuta.` |
| `stav` | Vypíše `LED nesviti.` |
| `echo Ahoj svete` | Vypíše `Prijaty text: Ahoj svete` |
| `ahoj` | Ohlásí neznámý příkaz a zobrazí nápovědu. |
| prázdný řádek | Vypíše `Prijato: []`, další akci neprovede. |
| více než 64 znaků | Odmítne celý řádek; další příkaz opět funguje. |

## Jak program funguje

1. `setup()` připraví LED a sériovou komunikaci.
2. `loop()` pomocí `Serial.available()` kontroluje přijatá data.
3. `Serial.read()` přečte jeden znak a připojí ho k proměnné `radek`.
4. Po přijetí `\n` nebo `\r` zavolá `zpracujRadek()`, která vybere akci pomocí `if`.
5. Vyprázdní řádek a přijímá další příkaz.

Program zpracuje CR i LF a dvojici CRLF bere jako jeden konec řádku. Maximální délka je
64 bajtů před ukončením řádku (u textu bez diakritiky 64 znaků). Nepoužívá
`delay()` ani čekání na celý řádek. Objekt `String` zde zjednodušuje práci s textem
pro začátečníky; velikost přijímaného řádku je omezená kvůli malé paměti Una.

## Úkoly

1. Přidej příkaz `jmeno`, který vypíše tvoje jméno.
2. Přidej příkaz `prepni`, který změní stav LED na opačný.
3. Přidej počítadlo neprázdných příkazů a příkaz `pocet` pro jeho zobrazení.
4. Vysvětli, proč se při příliš dlouhém řádku zahazuje i jeho zbytek.
