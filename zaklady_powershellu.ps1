# Komentovaný průvodce konzolí Windows PowerShell 5.1 / PowerShell 7.
# Start -> vyhledej PowerShell -> otevři běžné okno (bez správce).
# Přejdi do složky se skriptem: Set-Location 'C:\cesta\k\projektu'
# Spuštění: .\zaklady_powershellu.ps1
# Pokud Windows blokuje místní skripty, můžeš pro aktuální okno nastavit:
# Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
# U staženého souboru po kontrole obsahu: Unblock-File .\zaklady_powershellu.ps1
# Firemní zásady mohou mít přednost. Neměň zásady pro celý počítač.
#
# Skript vytvoří vlastní cvičnou složku v dočasném adresáři Windows.
# Klonování projektu i instalace Debianu jsou volitelné, nic se neodesílá.
# Git musí být nainstalovaný ve Windows, instalace v Debianu nestačí.
# Pokud chybí, nainstaluj Git for Windows z oficiální stránky:
# https://git-scm.com/downloads/win
# GitHub CLI (gh) je volitelné a pro toto cvičení není potřeba.
# Potom otevři nové okno PowerShellu, aby se obnovila proměnná PATH.

$ErrorActionPreference = 'Stop' # Chyby cmdletů zastaví skript.
# Externí programy (git, wsl) kontrolujeme přes $LASTEXITCODE.

# Funkce obalí Git, aby neúspěšný externí příkaz nezůstal bez povšimnutí.
function Invoke-Git {
    & git @args # & spustí příkaz; @args předá jednotlivé argumenty funkce.
    if ($LASTEXITCODE -ne 0) {
        throw "Git skončil s chybou $LASTEXITCODE."
    }
}

# 1. ADRESÁŘE A SOUBORY
Write-Host "`n1. Adresáře a soubory" # `n je nový řádek.
Get-Location                         # Jako pwd v Bashi.
Get-ChildItem                        # Obsah adresáře, obdoba ls.
# PowerShell má aliasy pwd, ls, cd, ale zde používáme plné názvy příkazů.
# Proměnné začínají $. Join-Path bezpečně sestaví cestu.
$cviceni = Join-Path ([System.IO.Path]::GetTempPath()) ('zaklady-powershellu-' + [guid]::NewGuid())
$poznamky = Join-Path $cviceni 'poznamky'
New-Item -ItemType Directory -Path $poznamky -Force | Out-Null
Write-Host "Cvičná složka: $cviceni"

# Push-Location uloží původní adresář, Pop-Location se do něj vrátí.
# finally zajistí návrat i tehdy, když uvnitř nastane chyba.
Push-Location $cviceni
try {
    Set-Location $poznamky
    New-Item -ItemType File -Path 'prazdny.txt' | Out-Null
    Get-Location
    Set-Location ..                  # .. znamená nadřazený adresář.
    Get-ChildItem -Force             # Včetně skrytých položek.

    # 2. VSTUP, VÝSTUP A ROURY
    Write-Host "`n2. Vstup a výstup"
    $jmeno = Read-Host 'Jak se jmenuješ? (Enter = Student)'
    if ([string]::IsNullOrWhiteSpace($jmeno)) {
        $jmeno = 'Student'
    }
    # Dvojité uvozovky dosazují proměnné, jednoduché zachovají doslovný text.
    Write-Output "Ahoj, $jmeno!"
    Write-Output 'Proměnná $jmeno se v jednoduchých uvozovkách nedosadí.'

    $pozdrav = Join-Path $poznamky 'pozdrav.txt'
    # Set-Content přepíše obsah, Add-Content připojí další řádek.
    # Explicitní UTF8 umožní uložit české znaky.
    Set-Content -LiteralPath $pozdrav -Value "Ahoj, $jmeno!" -Encoding UTF8
    Add-Content -LiteralPath $pozdrav -Value 'Učím se PowerShell.' -Encoding UTF8
    Get-Content -LiteralPath $pozdrav -Encoding UTF8

    # | předává objekty z jednoho příkazu do druhého, nejen text.
    $pocet = Get-Content -LiteralPath $pozdrav -Encoding UTF8 | Measure-Object -Line
    Write-Host "Počet řádků: $($pocet.Lines)"
    'hruška', 'jablko', 'hruška' | Sort-Object -Unique
    Get-ChildItem $poznamky | Where-Object { $_.Extension -eq '.txt' } |
        Select-Object Name, Length
    # $_ je aktuální objekt v rouře, -eq porovnává rovnost.

    # > přepíše soubor, >> připojí výstup; kódování se liší podle verze PS.
    # Proto pro český text výše používáme -Encoding UTF8.
    'Prvni radek' > (Join-Path $poznamky 'vystup.txt')
    'Druhy radek' >> (Join-Path $poznamky 'vystup.txt')
    # PowerShell nemá bashové přesměrování vstupu <. Soubor čteme Get-Content.
    # Chybový proud má číslo 2, 2> jej uloží, 2>&1 připojí k výstupu.
    # Continue ponechá tuto ukázkovou chybu neukončující.
    Write-Error 'Ukázková chyba.' -ErrorAction Continue 2> (Join-Path $poznamky 'chyba.txt')
    Get-Content (Join-Path $poznamky 'chyba.txt')

    Copy-Item -LiteralPath $pozdrav -Destination (Join-Path $poznamky 'kopie.txt')
    Rename-Item -LiteralPath (Join-Path $poznamky 'kopie.txt') -NewName 'zaloha.txt'
    Remove-Item -LiteralPath (Join-Path $poznamky 'prazdny.txt')

    # 3. GIT: MÍSTNÍ HISTORIE
    Write-Host "`n3. Git v místním cvičném repozitáři"
    if (Get-Command git -ErrorAction SilentlyContinue) {
        $gitCviceni = Join-Path $cviceni 'git-cviceni'
        New-Item -ItemType Directory -Path $gitCviceni | Out-Null
        Set-Location $gitCviceni
        Invoke-Git init
        # Identita jen pro tento repozitář, globální nastavení se nemění.
        Invoke-Git config --local user.name 'Student'
        Invoke-Git config --local user.email 'student@example.invalid'
        Set-Content ukazka.txt 'Můj první soubor v Gitu.' -Encoding UTF8
        Invoke-Git status             # Přehled změn a nových souborů.
        Invoke-Git add ukazka.txt      # Příprava konkrétního souboru.
        Invoke-Git diff --cached      # Co bude součástí commitu.
        Invoke-Git commit -m 'Přidat první cvičný soubor'
        Add-Content ukazka.txt 'Druhý řádek.' -Encoding UTF8
        Invoke-Git diff                # Změny před git add.
        Invoke-Git add ukazka.txt
        Invoke-Git commit -m 'Doplnit druhý řádek'
        Invoke-Git log --oneline       # Historie commitů.
        Invoke-Git status --short      # Prázdný výpis = čistý adresář.
    } else {
        Write-Host 'Git není dostupný. Ukázka Gitu byla přeskočena.'
    }

    # Další příkazy pro reálný projekt (zde se nespouštějí):
    # git switch -c moje-uprava        # Nová pracovní větev.
    # git add zaklady_pythonu.py
    # git commit -m 'Upravit ukázku Pythonu' # Uložení lokálně.
    # git pull --ff-only               # Aktualizace; nejdřív dokonči úpravy.
    # git push -u origin moje-uprava   # Odeslání; vyžaduje oprávnění.

    # 4. VOLITELNÉ STAŽENÍ PROJEKTU Z GITHUBU
    Write-Host "`n4. Stažení projektu"
    # Veřejný repozitář stáhneme přes HTTPS bez účtu a bez GitHub CLI.
    # Soukromý repozitář vyžaduje přihlášení a oprávnění.
    $odpoved = Read-Host 'Stáhnout AntoninMicka/ZakladyProgramovani do domácí složky Projekty? (ano/ne)'
    if ($odpoved -eq 'ano') {
        if (!(Get-Command git -ErrorAction SilentlyContinue)) {
            throw 'Pro klonování nainstaluj Git ve Windows.'
        }
        $projekty = Join-Path $HOME 'Projekty'
        New-Item -ItemType Directory -Path $projekty -Force | Out-Null
        Set-Location $projekty
        if (Test-Path -LiteralPath 'ZakladyProgramovani') {
            Write-Host 'Cesta ZakladyProgramovani již existuje; klonování přeskočeno.'
        } else {
            Invoke-Git clone https://github.com/AntoninMicka/ZakladyProgramovani.git
        }
        if (Test-Path -LiteralPath 'ZakladyProgramovani/.git' -PathType Container) {
            Invoke-Git -C ZakladyProgramovani status
            Invoke-Git -C ZakladyProgramovani remote -v
        }
    } else {
        Write-Host 'Klonování přeskočeno. Později použij git clone https://github.com/AntoninMicka/ZakladyProgramovani.git.'
    }
} finally {
    Pop-Location
}

# 5. VOLITELNÁ INSTALACE DEBIANU DO WSL 2
# Tato část patří do Windows. Vyžaduje Windows 11 nebo Windows 10 od
# verze 2004, sestavení 19041, a zapnutou virtualizaci v UEFI/BIOS.
# Podrobnosti: https://learn.microsoft.com/en-us/windows/wsl/install
Write-Host "`n5. Volitelná instalace Debianu do WSL 2"
$instalovat = Read-Host 'Spustit instalaci Debianu do WSL? (ano/ne)'
if ($instalovat -eq 'ano') {
    Write-Host 'Potvrď dialog správce. Po dokončení si přečti výsledek a zavři instalační okno.'
    # Nevyžadujeme spouštět celé cvičení jako správce. Zvýšená oprávnění
    # dostane jen instalační příkaz po potvrzení dialogu Windows (UAC).
    $instalace = Start-Process -FilePath 'powershell.exe' -Verb RunAs -Wait -PassThru -ArgumentList @(
        '-NoProfile', '-NoExit', '-Command',
        'wsl --install -d Debian; Write-Host "Po instalaci podle potreby restartujte Windows."'
    )
    # -NoExit ponechá instalační okno otevřené pro čtení výsledku.
    # Po dokončení ho zavři, aby mohl tento skript pokračovat.
    Write-Host "Instalační okno bylo zavřeno (kód procesu: $($instalace.ExitCode))."
    Write-Host 'Výsledek instalace ověř podle výpisu WSL, samotný kód okna ho nepotvrzuje.'
} else {
    Write-Host 'Instalace přeskočena.'
}
# Po instalaci případně restartuj Windows. V novém PowerShellu ověř:
# wsl --update
# wsl --list --verbose              # U Debianu má být VERSION 2.
# Pokud má existující Debian VERSION 1: wsl --set-version Debian 2
# wsl -d Debian                     # Otevře linuxovou konzoli.
# Při prvním spuštění vytvoř linuxové jméno a heslo. Heslo není při psaní vidět.
# Další linuxové kroky najdeš v INSTALACE_WSL2_DEBIAN.txt.
# Windows a Debian mají oddělené instalace nástrojů i místní kopie projektu.

Write-Host "`nHotovo. Cvičné soubory zůstávají v: $cviceni"
# Nápověda: Get-Help Get-ChildItem -Examples
# Historie příkazů: šipka nahoru. Přerušení příkazu: Ctrl+C.
