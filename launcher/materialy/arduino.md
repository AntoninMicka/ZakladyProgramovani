# Arduino Uno: sériová linka, ADC a krokový motor

Program běží na simulovaném Arduino Uno. Přijímá textové příkazy, ovládá LED L,
čte napětí z potenciometru a převádí je na polohu ručičky krokového motoru.
Hlavní zdroj je `druha_hodina/src/main.cpp`, zapojení `diagram.json`.

## Spuštění

1. Akcí **Sestavit Arduino firmware** vytvoř HEX a ELF. Je potřeba PlatformIO.
   První sestavení může stahovat veřejné balíčky a potřebovat internet.
2. Akcí **Otevřít projekt ve VSCodiu / VS Code** otevři složku projektu.
   Nainstaluj a aktivuj rozšíření Wokwi podle původního README.
3. V editoru vyber `wokwi.toml` a spusť **Wokwi: Start Simulator**.
4. V sériovém monitoru Wokwi napiš `pomoc`, Enter; potom `zapni`, `stav`, `vypni`.

Otevření editoru samo simulaci nespouští. Pro konzolové ověření lze samostatnou
akcí sestavit a spustit Wokwi CLI na šest virtuálních sekund. Ta potřebuje
`WOKWI_CLI_TOKEN` v prostředí a může čerpat CI kvótu. Vizuální ovládání periferií
je nejpřehlednější přímo v rozšíření editoru.

## Co má být vidět

Vestavěná LED reaguje na příkazy a monitor vrací přijatý řádek. Potenciometr
na A0 mění měřené napětí a požadovanou polohu ručičky:

- 0 V: 12 hodin, nahoře;
- přibližně 2,5 V: 3 hodiny, vpravo;
- 5 V: 6 hodin, dole.

ADC měří přibližně jednou za sekundu, takže změna není okamžitá. Dokončení
převodu obsluhuje přerušení; tisk a pohyb probíhají v hlavní smyčce.

## Co se učíš

Přijímat jednotlivé znaky, poznat konec řádku, rozhodnout podle příkazu a
bez blokujícího čekání obsluhovat více činností. Dále převádět číslo ADC 0–1023
na napětí a počet kroků motoru. Zdroj ukazuje rozdíl mezi přerušením a běžným cyklem.
Jde o simulaci: skutečný motor potřebuje napájení výkonové části a nastavení
proudového limitu A4988, jak vysvětluje původní README.
