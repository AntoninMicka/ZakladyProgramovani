# ECU simulátor motoru a společný řadič

Projekt propojuje model čtyřtaktního motoru v Pythonu a řídicí jednotku v C++.
GUI ukazuje písty, kliku, fáze válců, graf otáček a telemetrii. V samostatné
záložce můžeš upravovat C++ řadič, přeložit změnu a použít ji v simulaci.

## Nejrychlejší spuštění

Vyber **Spustit ECU simulátor s GUI**. Otevře se vlastní okno motoru, centrální
spouštěč zůstane otevřený. Výchozí Mock používá lokálně přeložený společný
`ecu_controller.h`; nepotřebuje Wokwi token. Je potřeba C++ překladač a Python
prostředí simulátoru s pySerial. Spouštěč přednostně použije `simulator/.venv`.

Pokud prostředí chybí, z kořene repozitáře připrav:

```bash
python3 -m venv simulator/.venv
simulator/.venv/bin/python -m pip install -r simulator/requirements.txt
```

Pro GUI musí mít systém Tk (`python3-tk` na Debianu/Ubuntu). Pro společnou ECU
potřebuješ `g++` nebo `clang++`. Spouštěč nic automaticky neinstaluje.

## Jak simulace pracuje

Model motoru vytváří hrany CKP/CMP. Stejný C++ řadič jako ve firmware z nich
získává otáčky a fázi cyklu, potom řídí vstřikovače a zapalování. Dokončené pulzy
se vracejí do modelu a ovlivňují motor. V Mock běží vše podle společného virtuálního
času, takže můžeš děj zpomalit nebo pozastavit.

Pedál zatím přímo určuje palivo v ECU. Plný pedál odpovídá 3ms vstřiku,
35 % přibližně 1,05 ms. Python moment podruhé nenásobí pedálem. **Automatický
regulátor požadovaných otáček zatím není hotový — je studentským úkolem.**

## Ovládání okna ECU

- **Motor:** pedál, zátěž, pauza a rychlost zobrazení/simulace.
- **Schéma motoru:** průhledový řez se snímači, vstřikovači, cívkami a ECU.
  Kliknutím zobrazíš úlohu dílu a živé hodnoty; SVG lze přiblížit a uložit.
- **Telemetrie:** aktuální hodnoty a historie s možností exportu.
- **Editor ECU:** otevři `firmware/include/ecu_controller.h`, najdi označenou
  `update_control(now)`, uprav ji a zvol **Použít v simulaci**.
- **Wokwi:** správa externího hardwarového simulátoru. Tato větev vyžaduje další
  nástroje a aktivaci; podrobnosti jsou v README simulátoru.

Úspěšné použití nové ECU začne od času nula; chyba překladu ponechá starou ECU
běžet. Parametry pedálu a zátěže se při aplikaci zachovají.

## Aktuální studentský úkol

V záložce **Úkoly pro studenta** je skutečné zadání automatické regulace otáček,
načítané přímo ze souboru simulátoru. Student má změnit význam pedálu na cílové
otáčky a palivo řídit podle rozdílu cíle a změřených otáček. Kód regulátoru
spouštěč nedoplňuje.

Pro tento pokus nepoužívej parametr `--rpm`: ten zapne stolici s přímo drženými
otáčkami a skryl by chyby regulátoru. Při stejné poloze pedálu měň zátěž a sleduj,
zda se upravený řadič dokáže vrátit k cílovým otáčkám.

## Auto, palubní deska a CAN

Akce **Spustit simulaci auta s palubní deskou** otevře nový pohled nad týmž motorem
a C++ regulátorem. V záložce **Auto / palubní deska** zvol `D`, přidej plyn a sleduj
řazení šestistupňové převodovky. Brzdou a volantem ovládej podvozek, přilnavostí
vlevo/vpravo připrav kluzký či nestejný povrch. ABS moduluje jednotlivé brzdy,
ESP přibrzďuje kolo a omezuje moment při rozdílu požadovaného a skutečného stáčení.
Převodovka, otevřený přední diferenciál a kola se zpětně projeví v zatížení motoru.

Pod přístroji jsou nové senzory a monitor CAN s ID, bajty a dekódovanými hodnotami.
Při vypnutí CAN po timeoutu zmizí zastaralá data přístrojů a pohon přejde do neutrálu;
základní brzdy zůstávají funkční. Pauza a zpomalení platí pro celé auto.

Jde o první výukový model, nikoli detailní dynamiku skutečného auta. Přenos CAN je
lokální logická simulace, bez fyzického transceiveru. Podrobný návod a další etapy:
[model auta](../../simulator/docs/auto.md).
