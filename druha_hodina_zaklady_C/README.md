# Druhá hodina: základy C

Převod Python materiálů ze složky `prvni_hodina` do standardního **C17**:

- `zaklady_c.c` odpovídá `zaklady_pythonu.py`: devět témat, české komentáře a pokusy.
- `ukol_soubory.c` odpovídá `ukol_soubory.py`: řešení rozdělení čísel do souborů podle parity.
- `vstup.txt` obsahuje stejných 20 čísel jako původní soubor.

Původní soubory zůstávají zachované. Bash, PowerShell a instalační text nejsou
Python programy, proto se nepřevádějí.

## Překlad a spuštění (Linux nebo Debian ve WSL)

Potřebuješ překladač GCC. Na Debianu/Ubuntu jej případně nainstaluj:

```bash
sudo apt update
sudo apt install build-essential
```

Z kořene repozitáře spusť:

```bash
cd druha_hodina_zaklady_C
gcc -std=c17 -Wall -Wextra -Wpedantic zaklady_c.c -o zaklady_c
./zaklady_c
gcc -std=c17 -Wall -Wextra -Wpedantic ukol_soubory.c -o ukol_soubory
./ukol_soubory
```

C se nejdříve překládá do spustitelného programu. Po změně `.c` souboru překlad
zopakuj. Použít lze i Clang se stejnými přepínači místo `gcc`.

Úkol spouštěj z této složky: relativní cesty v C vycházejí z pracovního adresáře.
To se liší od původního Python skriptu, který zjišťoval cestu ke svému souboru.
Výstupy `sude.txt` a `liche.txt` se při každém spuštění přepisují.

## Kontrola úkolu

Program načte a ověří čísla a rozdělí je do výstupních souborů. Musí platit:

- V `sude.txt` jsou jen sudá čísla, včetně nuly.
- V `liche.txt` jsou jen lichá čísla.
- Pořadí a opakování se zachovají; celkový počet čísel je stejný jako na vstupu.
- Pro vstup `3`, `8`, `0`, `-5` na samostatných řádcích dostaneš sudá `8`, `0`
  a lichá `3`, `-5`.

## Rozdíly oproti Pythonu

Typy se deklarují, příkazy končí středníkem a bloky vymezují složené závorky.
Pole nemají automatické zvětšování. Řetězce jsou ukončené bajtem `\0`.
Slovník, množina, výřezy a seznamová komprehenze nemají přímou vestavěnou obdobu;
ukázka používá struktury, pole a cykly. Chyby se kontrolují návratovými hodnotami.
`int / int` dělí celočíselně směrem k nule; `^` není mocnina.
