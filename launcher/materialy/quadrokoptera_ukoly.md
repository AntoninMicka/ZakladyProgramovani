# Úkoly: snímač, regulátor a směšování

## 1. Podmínky aktivace

Zkus ARM při zvýšeném plynu, potom při příliš velkém náklonu. Zapiš, co vypíše
monitor. Najdi ve zdroji podmínku, která aktivaci odmítla. Podmínky neodstraňuj.

## 2. Čtyři výstupy

S vodorovným senzorem a středovým joystickem zvyš plyn. Porovnej všechny čtyři
výstupy. Pak vychyl joystick doprava a zjisti, která dvojice přidá a která ubere.
Nakresli do sešitu rozmístění motorů v konfiguraci X.

## 3. Napodobení náklonu

Po kalibraci nastav akceleraci X=0, Y=0,5 a Z=0,866 g. To napodobuje statický
náklon přibližně 30°. Sleduj odhad úhlu i rozdíly motorových výstupů.
Vysvětli, proč tento pokus sám neprokazuje, že by dron ve skutečnosti držel polohu.

## 4. Vlastní drobná úprava

S učitelem změň jednu regulační konstantu nebo rozsah požadavku joysticku.
Nejdřív si zapiš původní hodnotu. Porovnej odezvu na stejnou změnu vstupu před
úpravou a po ní. Zbytek nastavení ponech stejný, aby bylo jasné, co rozdíl způsobilo.

## 5. Test čistých výpočtů

V `tests/controller_test.cpp` prohlédni testy směšovače a aktivace.
Navrhni další konkrétní vstup a očekávaný výsledek. Postup jeho překladu je
v README. Zkoušíš výpočet na počítači, nikoli letový test.
