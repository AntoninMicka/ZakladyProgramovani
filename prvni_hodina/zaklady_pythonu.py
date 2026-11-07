"""Spustitelný průvodce základní syntaxí Pythonu 3.

Spuštění v terminálu: python3 zaklady_pythonu.py
Program nepotřebuje žádné další knihovny ani vstup z klávesnice.
"""

# 1. KOMENTÁŘE, PROMĚNNÉ A ZÁKLADNÍ TYPY
# Komentář začíná znakem # a Python ho nevykonává.
# Hodnotu přiřadíme pomocí =. Typ proměnné určí Python podle hodnoty.
jmeno = "Eva"             # str: textový řetězec
vek = 20                  # int: celé číslo
vyska = 1.72              # float: desetinné číslo (píšeme tečku)
je_student = True         # bool: pravdivostní hodnota True nebo False
prezdivka = None          # None označuje nepřítomnost hodnoty

# print() vypisuje hodnoty. f-řetězec vloží výrazy ze složených závorek.
print("1. Proměnné a typy")
print(f"{jmeno} má {vek} let a měří {vyska} m.")
print(f"Student: {je_student}, přezdívka: {prezdivka}")


# 2. OPERÁTORY
# + součet, - rozdíl, * součin, / dělení, // celočíselné dělení,
# % zbytek po dělení, ** mocnina.
print("\n2. Operátory")  # \n vloží nový řádek.
print(f"7 + 2 = {7 + 2}, 7 / 2 = {7 / 2}, 7 // 2 = {7 // 2}")
print(f"7 % 2 = {7 % 2}, 2 ** 3 = {2 ** 3}")


# 3. PODMÍNKY A ODSAZENÍ
# Blok začíná dvojtečkou a je odsazený, obvykle čtyřmi mezerami.
# == porovnává hodnoty; = přiřazuje. Další porovnání: !=, <, <=, >, >=.
# and znamená „a zároveň“, or „nebo“, not obrací pravdivost.
print("\n3. Podmínky")
if vek >= 18 and je_student:
    print("Jsi dospělý student.")
elif vek >= 18:
    print("Jsi dospělý.")
else:
    print("Ještě ti nebylo 18 let.")


# 4. SEZNAMY A CYKLUS FOR
# Seznam (list) může obsahovat více položek a lze ho měnit.
# Indexy začínají nulou. Záporný index -1 označuje poslední položku.
print("\n4. Seznam a cyklus for")
ovoce = ["jablko", "hruška", "švestka"]
ovoce.append("meruňka")
print(f"První: {ovoce[0]}, poslední: {ovoce[-1]}, počet: {len(ovoce)}")
print(f"První dvě položky (výřez): {ovoce[:2]}")

for poradi, plod in enumerate(ovoce, start=1):
    print(f"{poradi}. {plod}")

# range(1, 4) vytvoří posloupnost 1, 2, 3; horní mez se nezahrnuje.
for cislo in range(1, 4):
    print(f"{cislo} na druhou = {cislo ** 2}")


# 5. CYKLUS WHILE, CONTINUE A BREAK
# while opakuje blok, dokud je podmínka pravdivá.
# continue přeskočí zbytek aktuálního průchodu, break ukončí cyklus.
print("\n5. Cyklus while")
pocitadlo = 0
while pocitadlo < 5:
    pocitadlo += 1  # Zkrácený zápis pro pocitadlo = pocitadlo + 1.
    if pocitadlo == 2:
        continue
    if pocitadlo == 4:
        break
    print(pocitadlo)  # Vypíše 1 a 3.


# 6. SLOVNÍK, N-TICE A MNOŽINA
# dict ukládá dvojice klíč: hodnota.
# tuple je neměnná posloupnost; set uchovává jedinečné prvky.
print("\n6. Další kolekce")
student = {"jmeno": jmeno, "vek": vek}
student["obor"] = "informatika"
for klic, hodnota in student.items():
    print(f"{klic}: {hodnota}")

souradnice = (10, 20)
x, y = souradnice  # Rozbalení dvojice do dvou proměnných.
unikatni_cisla = {1, 2, 2, 3}
print(f"Souřadnice: x={x}, y={y}")
print(f"Jedinečná čísla: {sorted(unikatni_cisla)}")
print(f"Je číslo 2 v množině? {2 in unikatni_cisla}")


# 7. FUNKCE
# def definuje funkci, parametry přijímají hodnoty, return vrací výsledek.
# : str a -> str jsou typové anotace: pomáhají čtenáři a nástrojům,
# samotný Python podle nich typy při běhu nevynucuje.
def pozdrav(osoba: str, osloveni: str = "Ahoj") -> str:
    """Vrátí pozdrav; osloveni má výchozí hodnotu."""
    return f"{osloveni}, {osoba}!"


print("\n7. Funkce")
print(pozdrav(jmeno))
print(pozdrav("Petře", osloveni="Dobrý den"))


# 8. VÝJIMKY A PŘEVODY TYPŮ
# int() převádí text na celé číslo. Neplatný text vyvolá ValueError.
# try obsahuje operaci, která může selhat; except zachytí konkrétní chybu.
print("\n8. Zpracování chyby")
for text in ["42", "ahoj"]:
    try:
        prevedene_cislo = int(text)
    except ValueError:
        print(f"Text {text!r} nelze převést na celé číslo.")
    else:
        print(f"Převod se podařil: {prevedene_cislo}")


# 9. SEZNAMOVÁ KOMPREHENZE
# Stručné vytvoření seznamu: výraz, cyklus a volitelná podmínka.
print("\n9. Seznamová komprehenze")
ctverce_sudych = [n ** 2 for n in range(1, 7) if n % 2 == 0]
print(f"Druhé mocniny sudých čísel od 1 do 6: {ctverce_sudych}")


# VLASTNÍ POKUSY:
# - Změň vek a je_student a sleduj, jakou větev podmínky program vybere.
# - Přidej další ovoce nebo uprav horní mez range().
# - Zavolej funkci pozdrav() s vlastním jménem.
# - Volitelný vstup: jmeno = input("Jak se jmenuješ? ")
#   input() vždy vrací text; číslo získáš například pomocí int().
