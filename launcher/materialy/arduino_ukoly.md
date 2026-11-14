# Úkoly: Arduino a sériové příkazy

## 1. Vlastní příkazy

V `src/main.cpp` přidej příkaz `jmeno`, který vypíše tvoje jméno.
Přidej `prepni`, který obrátí stav LED. Po každé změně sestav firmware a restartuj Wokwi.

## 2. Počítadlo

Počítej neprázdné přijaté příkazy a přidej příkaz `pocet` pro výpis tohoto čísla.
Rozmysli, zda i příkaz `pocet` má sám počet zvýšit, a svou volbu napiš.

## 3. Zkouška hranic

Pošli prázdný řádek, neznámý příkaz a řádek delší než 64 znaků. Program musí
srozumitelně reagovat a potom znovu přijmout běžný krátký příkaz.
Vysvětli, proč po přeplnění bufferu nestačí zahodit jen jediný další znak.

## 4. Měření a ručička

Nastav potenciometr na 0, 2,5 a 5 V. Zapiš ADC hodnotu a polohu ručičky.
Najdi ve zdroji přepočet mezi ADC a počtem kroků. Uprav rozsah ručičky na menší
část ciferníku a ověř obě krajní polohy.

## Jak poznáš splnění

LED reaguje na tvoje příkazy, počítadlo odpovídá zvolené definici a po příliš
dlouhém řádku program dál funguje. ADC a krokový motor zůstávají funkční i během
sériové komunikace; nepřidávej čekání, které by vše zastavovalo.
