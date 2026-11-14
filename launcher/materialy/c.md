# Základy jazyka C

Tento projekt převádí první Python ukázky do standardního C17. Díky tomu můžeš
porovnat stejnou úlohu ve dvou jazycích. C se před spuštěním překládá na strojový
program; tlačítka spouštěče vždy nejdřív spustí překladač a teprve při úspěchu výsledek.

## Dva programy

**Základy C** (`zaklady_c.c`) obsahují proměnné, operátory, podmínky, cykly,
pole, funkce a převody textu. U každé ukázky najdeš české komentáře. Všimni si,
že typ proměnné deklaruješ předem a bloky ohraničují složené závorky.

**Rozdělení čísel** (`ukol_soubory.c`) načte `vstup.txt`, ověří celá čísla a
rozdělí je podle parity. `sude.txt` a `liche.txt` při každém spuštění přepíše.
Nula je sudá; pořadí, záporná čísla a opakování se zachovávají.

## Jak spouštěč překládá

Potřebuješ GCC nebo Clang. Na Debianu/Ubuntu je GCC součástí `build-essential`.
Spouštěč použije přepínače `-std=c17 -Wall -Wextra -Wpedantic`. Výsledný program
ukládá do ignorovaného adresáře `.cache/launcher/c`, nikoli mezi zdroje.
Soubory se ale čtou a zapisují v adresáři podprojektu, jak vyžadují původní příklady.
Přesný příkaz i případné chyby uvidíš ve Výstupu programu.

## Co sledovat

- Celočíselné dělení nevrací desetinnou část. Zkus porovnat `7 / 2` a `7.0 / 2`.
- Pole má určenou kapacitu. Přidání položky může vyžadovat i změnu jeho velikosti.
- Řetězec je posloupnost znaků ukončená nulovým znakem.
- Chybu při otevírání souboru nebo převodu textu musí program zkontrolovat.

Nejdřív se snaž předpovědět výpis, pak proveď jednu změnu a znovu překládej.
Když překlad selže, nespustí se stará binárka: spouštěč zobrazí chybu a zastaví akci.
Podrobný původní postup a rozdíly oproti Pythonu najdeš v záložce README / zdroj.
