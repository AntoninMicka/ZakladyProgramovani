#!/usr/bin/env bash
# Komentovaný průvodce konzolí v Debianu / WSL 2.
# Spuštění: bash zaklady_konzole.sh
# Řádky začínající # jsou komentáře. Znak $ z výzvy konzole neopisujeme.
# Skript vytváří cvičnou složku v /tmp a ponechá ji pro další prohlížení.
# Projekt z GitHubu stáhne pouze po odpovědi ano, nic neodesílá na server.

# Ukonči skript při chybě příkazu, použití neexistující proměnné nebo chybě
# v rouře. Jde o nastavení tohoto skriptu, není nutné pro běžnou konzoli.
set -euo pipefail

# 1. ADRESÁŘE A SOUBORY
# pwd vypíše aktuální adresář. ls vypíše jeho obsah.
# ~ označuje domovský adresář, . aktuální a .. nadřazený adresář.
printf '\n1. Adresáře a soubory\n'
pwd
ls

# Proměnnou přiřazujeme bez mezer kolem =. Její hodnotu čteme jako $nazev.
# $(prikaz) zachytí standardní výstup příkazu do proměnné.
# mktemp -d vytvoří nový unikátní adresář, takže nepřepíšeme staré cvičení.
cviceni=$(mktemp -d /tmp/zaklady-konzole.XXXXXX)
printf 'Cvičná složka: %s\n' "$cviceni"

# mkdir vytvoří adresář; -p dovolí vytvořit i chybějící nadřazené adresáře.
# Cesty v uvozovkách fungují také tehdy, když obsahují mezery.
mkdir -p "$cviceni/poznamky"
cd "$cviceni"
touch poznamky/prazdny.txt   # Vytvoří prázdný soubor, pokud neexistuje.
ls -la                      # -l: podrobnosti, -a: včetně skrytých souborů.
cd poznamky                 # Relativní cesta vůči aktuálnímu adresáři.
pwd
cd ..                       # Návrat do nadřazeného adresáře.

# 2. VSTUP, VÝSTUP A PŘESMĚROVÁNÍ
printf '\n2. Vstup a výstup\n'
# read načte řádek ze standardního vstupu (obvykle klávesnice).
# -r zachová zpětná lomítka. IFS= zachová mezery na okrajích vstupu.
printf 'Jak se jmenuješ? (Enter = Student): '
jmeno=''
IFS= read -r jmeno || true   # Konec vstupu zde nevadí, použijeme výchozí jméno.
jmeno=${jmeno:-Student}      # Použij Student, pokud je hodnota prázdná.

# printf vypisuje text; %s je místo pro textový argument, \n nový řádek.
# > přesměruje výstup do souboru a přepíše jeho dosavadní obsah.
# >> připojí výstup na konec souboru.
printf 'Ahoj, %s!\n' "$jmeno" > poznamky/pozdrav.txt
printf 'Učím se pracovat v konzoli.\n' >> poznamky/pozdrav.txt
cat poznamky/pozdrav.txt     # cat vypíše obsah souboru.

# < předá obsah souboru na standardní vstup příkazu.
printf 'Počet řádků v souboru: '
wc -l < poznamky/pozdrav.txt

# | (roura) propojí standardní výstup vlevo se vstupem vpravo.
# sort řadí řádky, uniq odstraní sousední duplicity.
printf 'hruška\njablko\nhruška\n' | sort | uniq

# Chybový výstup je samostatný proud (číslo 2).
# 2> uloží chyby do souboru; >&2 vypisuje na chybový výstup.
printf 'Ukázková zpráva na chybovém výstupu.\n' >&2
# Podmínka if otestuje návratový kód: 0 = úspěch, jiná hodnota = chyba.
if ls "$cviceni/neexistujici-soubor" 2> poznamky/chyba.txt; then
    printf 'Soubor existuje.\n'
else
    printf 'Očekávaná chyba byla zachycena do souboru:\n'
    cat poznamky/chyba.txt
fi

# cp kopíruje, mv přejmenuje nebo přesune, rm odstraní soubor.
cp poznamky/pozdrav.txt poznamky/kopie.txt
mv poznamky/kopie.txt poznamky/zaloha.txt
rm poznamky/prazdny.txt      # Mažeme jen prázdný soubor vytvořený výše.

# 3. GIT: MÍSTNÍ HISTORIE ZMĚN
printf '\n3. Git v místním cvičném repozitáři\n'
# command -v ověří, že je nástroj dostupný.
if ! command -v git >/dev/null 2>&1; then
    printf 'Chybí Git. V Debianu spusť: sudo apt install git\n' >&2
    exit 1
fi

mkdir "$cviceni/git-cviceni"
cd "$cviceni/git-cviceni"
git init                    # Vytvoří místní repozitář (skrytý adresář .git).

# Identita autora pouze v tomto cvičném repozitáři, nikoli globálně.
# V reálném projektu použij vlastní jméno a e-mail, případně GitHub noreply.
git config --local user.name 'Student'
git config --local user.email 'student@example.invalid'

printf 'Můj první soubor ve správě Gitu.\n' > ukazka.txt
git status                  # Ukáže nové a změněné soubory.
git add ukazka.txt           # Vybere konkrétní soubor pro příští commit.
git diff --cached           # Ukáže změny připravené k uložení.
git commit -m 'Přidat první cvičný soubor'

printf 'Druhý řádek.\n' >> ukazka.txt
git diff                    # Změny dosud nepřipravené příkazem git add.
git add ukazka.txt
git commit -m 'Doplnit druhý řádek'
git log --oneline           # Stručná historie commitů.
git status --short          # Prázdný výpis znamená čistý pracovní adresář.

# Commit ukládá historii lokálně. Push by ji odeslal na server.
# Další příkazy pro skutečný projekt (zde jsou jen komentáře):
# git switch -c moje-uprava  # Vytvoří a otevře novou pracovní větev.
# git status                # Před uložením zkontroluj změněné soubory.
# git diff                  # Prohlédni si vlastní úpravy.
# git add zaklady_pythonu.py # Připrav konkrétní upravený soubor.
# git commit -m 'Upravit ukázku základů Pythonu'
# git pull --ff-only        # Aktualizace z aktuálně sledované vzdálené větve.
#                           # Nejprve dokonči nebo odlož vlastní úpravy.
# git push -u origin moje-uprava
#                           # Odešle větev, vyžaduje oprávnění na GitHubu.

# 4. STAŽENÍ VEŘEJNÉHO REPOZITÁŘE BEZ ÚČTU
printf '\n4. Stažení AntoninMicka/ZakladyProgramovani\n'
# Veřejný repozitář lze přes HTTPS stáhnout bez účtu a bez GitHub CLI.
# Soukromý repozitář vyžaduje přihlášení a oprávnění.

printf 'Stáhnout projekt do ~/Projekty/ZakladyProgramovani? (ano/ne): '
odpoved=''
IFS= read -r odpoved || true
if [[ "$odpoved" == 'ano' ]]; then
    mkdir -p "$HOME/Projekty"
    cd "$HOME/Projekty"
    if [[ -e ZakladyProgramovani || -L ZakladyProgramovani ]]; then
        printf 'Cesta ZakladyProgramovani již existuje; klonování přeskočeno.\n'
    else
        git clone https://github.com/AntoninMicka/ZakladyProgramovani.git
    fi

    # -C spustí Git v dané složce bez nutnosti dalšího cd.
    if [[ -d ZakladyProgramovani/.git ]]; then
        git -C ZakladyProgramovani status
        git -C ZakladyProgramovani remote -v  # Adresy vzdáleného repozitáře.
    fi
else
    printf 'Klonování přeskočeno. Později můžeš ručně zadat:\n'
    printf 'mkdir -p ~/Projekty\ncd ~/Projekty\n'
    printf 'git clone https://github.com/AntoninMicka/ZakladyProgramovani.git\n'
fi

# Po stažení lze v konzoli zadat:
# cd ~/Projekty/ZakladyProgramovani
# kate zaklady_pythonu.py &
# python3 zaklady_pythonu.py

printf '\nHotovo. Cvičné soubory zůstávají v: %s\n' "$cviceni"
# Skript běží ve vlastním procesu, takže jeho cd nezmění adresář tvé konzole.
# Pro návrat k příkazům používej šipku nahoru; Ctrl+C přeruší běžící příkaz.
# Nápověda: prikaz --help, případně man prikaz (pokud máš nainstalované man).
