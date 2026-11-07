"""ÚKOL: Čtení a zápis do textových souborů.

Ve vstup.txt jsou náhodná celá čísla, každé na samostatném řádku.
Doplň program tak, aby sudá čísla zapsal do sude.txt a lichá do liche.txt.
V každém výstupním souboru bude opět jedno číslo na řádku.
Zachovej pořadí čísel i jejich případná opakování.

Spuštění: python3 ukol_soubory.py
Ve Windows můžeš použít také: py ukol_soubory.py

Postup:
1. Projdi jednotlivé řádky načteného obsahu pomocí cyklu for.
2. Převeď text řádku na celé číslo pomocí int().
3. Pomocí zbytku po dělení (%) rozhodni, zda je číslo sudé, nebo liché.
4. Zapiš číslo do příslušného souboru metodou write().
   write() očekává text a nový řádek nepřidává automaticky.

Kontrola řešení:
- V sude.txt budou jen čísla dělitelná dvěma (patří sem i nula).
- V liche.txt budou jen lichá čísla.
- Součet počtů řádků obou výstupů bude roven počtu vstupních čísel.
- Pro zkušební vstup 3, 8, 0, -5 (každé číslo na vlastním řádku)
  bude sude.txt obsahovat 8 a 0; liche.txt bude obsahovat 3 a -5.

POZOR: Spuštění vytvoří výstupní soubory, případně přepíše jejich obsah.
"""

from pathlib import Path


# Soubory hledáme vedle tohoto skriptu, bez ohledu na to, odkud ho spustíš.
adresar = Path(__file__).resolve().parent

# Režim "r" otevře existující soubor pro čtení.
# with po skončení bloku soubor automaticky zavře, i při chybě.
with open(adresar / "vstup.txt", "r", encoding="utf-8") as vstup:
    obsah = vstup.read()  # Načte celý obsah jako jeden textový řetězec.

# Režim "w" vytvoří soubor pro zápis; existující obsah se smaže.
# Otevíráme výstupy až po úspěšném načtení vstupního souboru.
with open(adresar / "sude.txt", "w", encoding="utf-8") as sude:
    with open(adresar / "liche.txt", "w", encoding="utf-8") as liche:
        # Procházíme řádky postupně, takže zachováme pořadí i opakování.
        for radek in obsah.splitlines():
            cislo = int(radek)  # Převede text řádku na celé číslo.
            if cislo % 2 == 0:  # Sudá jsou i nula a záporné násobky dvou.
                sude.write(f"{cislo}\n")
            else:
                liche.write(f"{cislo}\n")

print(f"Načteno {len(obsah.splitlines())} řádků ze souboru vstup.txt.")
print("Sudá čísla byla zapsána do sude.txt a lichá do liche.txt.")
