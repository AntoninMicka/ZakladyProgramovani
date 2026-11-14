# Úkol pro studenta: pedálem zvol otáčky, ECU určí palivo

## Co už simulátor umí

Pedál je vstup pro ECU. ECU určuje délku vstřiku a motor na palivo reaguje.
Stejná řídicí funkce běží v Mock i ve firmware pro Wokwi. Zatím záměrně funguje
jednoduchý převod: více sešlápnutý pedál znamená více paliva. Regulátor otáček
zatím není napsaný — to je tvůj úkol.

Představ si tempomat: řidič zadá cíl a elektronika přidává nebo ubírá podle toho,
jak moc skutečná rychlost za cílem zaostává. Tady místo rychlosti auta sleduješ
otáčky motoru.

## Kde budeš pracovat

Otevři v záložce **Editor ECU** soubor
`firmware/include/ecu_controller.h`. Najdi označenou funkci **`update_control(now)`**.
Čísla v ní znamenají:

| Jméno | Význam |
| --- | --- |
| `accelerator` | poloha pedálu: 0 = puštěný, 0,5 = polovina, 1 = plný pedál |
| `rpm` | skutečné otáčky, které ECU změřila z CKP |
| `requested_rpm` | místo pro tvoje požadované otáčky; nyní -1 = nepoužito |
| `injection_us` | tvůj výstup: délka vstřiku v mikrosekundách |
| `now` | čas od začátku běhu v mikrosekundách |

Funkce se volá každých 10 ms virtuálního času. Jedna sekunda má 1 000 000 µs.
Dávka 1500 µs tedy znamená otevření vstřikovače na 1,5 ms. O skutečné sepnutí
pinů se už postarají další části řadiče.

## Zadání

1. Zvol rozsah cílových otáček, například 800 až 3000 ot/min. Pedál na nule má
   znamenat dolní cíl, plně sešlápnutý pedál horní cíl. Výsledek zapisuj do
   `requested_rpm`, aby byl vidět také v diagnostice.
2. Porovnej požadované otáčky se skutečnými `rpm`. Jak poznáš, že má motor zrychlit?
   A jak poznáš, že už je potřeba ubrat?
3. Podle tohoto rozdílu uprav délku vstřiku `injection_us`. Udržuj ji v rozsahu
   0 až 20000 µs. Pro výpočet se záporným rozdílem používej nejdříve desetinnou
   pomocnou proměnnou: `injection_us` je nezáporné celé číslo. Zápornou dávku
   nejprve omez na nulu, teprve potom ji do něj ulož.
4. Vyzkoušej, zda se motor po změně zatížení vrátí přibližně ke stejnému cíli.
   Pokud otáčky neustále přestřelují a padají, přemýšlej, zda nepřidáváš moc prudce.

Způsob regulace navrhni s učitelem. Výchozí soubor neobsahuje hotové řešení ani PID.
Můžeš si do `EcuController` přidat proměnné, které si budou pamatovat minulý stav.

## Jak úpravu zkoušet

```bash
# Z adresáře simulator, bez --rpm:
.venv/bin/python main.py --gui --mode mock
```

- V editoru uprav funkci a stiskni **Použít v simulaci**. Nová ECU se přeloží
  a simulace začne znovu od času nula. Chyba překladu ponechá původní ECU běžet.
- Zvol přibližně 25 %, 50 % a 75 % pedálu. Zapiš si cíl, skutečné otáčky a dávku.
- Při stejném pedálu změň zátěž například z 12 na 20 Nm a zase zpět.
- Sleduj graf a telemetrii. Při uvolněném pedálu má nový regulátor podle tohoto
  zadání držet dolní cíl, nikoli automaticky vypnout palivo.

Nepoužívej `--rpm`: to je zkušební stolice, která otáčky drží přímo a zakryla by
chyby tvého regulátoru. Neměň přímo proměnnou `rpm`, Python model, CKP/CMP ani
časování vstřikovacích pinů. Otáčky ovlivňuj **jen množstvím paliva přes ECU**.

V Mock telemetrii najdeš `bridge.controller.requested_rpm` a `injection_us`;
textový výpis používá `ECU_rpm_goal` a `ECU_fuel`. Ve Wokwi obdobné hodnoty vypisuje
MCU jako `RPM_GOAL` a `FUEL_US` do diagnostiky. Kanál TPS v tomto výukovém zapojení
předává pedál; jeho kalibrace vychází z `config/engine.json`.

Model je zjednodušený: zvolený cíl musí být dosažitelný při dané zátěži a povolené
dávce. Chování při startování skutečného motoru ani jeho vzduchovou cestu tento
úkol neřeší. MAP a lambda jsou orientační ukazatele, nikoli vstupy tohoto úkolu.
