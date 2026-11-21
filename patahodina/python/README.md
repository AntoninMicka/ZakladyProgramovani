# Pátá hodina v Pythonu: objekty, generika a dědičnost

Dvě hotové ukázky používají stejných 30 souborů ze složky `../kontakty` jako
C++ programy. Stačí **Python 3.10 nebo novější**, bez instalace dalších balíčků.

## Spuštění

Z kořene repozitáře:

```bash
# Bez argumentu se program nejprve zeptá na formát:
python3 patahodina/python/sablony/main.py
python3 patahodina/python/dedicnost/main.py

# Formát lze zadat přímo: xml, json, vcard, csv nebo txt.
python3 patahodina/python/sablony/main.py json
python3 patahodina/python/dedicnost/main.py xml

# Volitelně zadej vlastní složku kontaktů:
python3 patahodina/python/dedicnost/main.py csv patahodina/kontakty/csv

# Stejné akce jsou dostupné ve společném grafickém spouštěči:
python3 spustit.py
# Nebo přes jeho terminálové rozhraní:
python3 spustit.py --run kontakty --action python_sablony
python3 spustit.py --run kontakty --action python_dedicnost

python3 -m unittest discover -s patahodina/python/tests -v
```

Výstup obou variant obsahuje šest kontaktů. Výchozí data se hledají podle
umístění skriptu, takže příklad funguje i při spuštění z jiné pracovní složky.
Chybný vstup se oznámí na stderr a program vrátí kód 1; chyba argumentů vrátí
kód 2. Při vadném souboru se nevypisuje neúplná databáze.

## Objekty a společný kód

Třída popisuje data a chování, objekt je její konkrétní instance.
`Kontakt` je datová třída vytvořená pomocí `@dataclass`: každý kontakt má
atributy `jmeno`, `email` a `telefon`. `db` je objekt databáze. Jeho konstruktor
`__init__()` vytvoří vlastní seznam `self.data`; `self` označuje právě ten
objekt, na kterém metodu voláme. `db.nacti()` seznam naplní a `db.zobraz()`
jej vypíše. Seznam vytvořený v konstruktoru se nesdílí mezi databázemi.

`spolecne.py` obsahuje čtečky a jediný algoritmus pro načtení složky.
`Protocol` vyjadřuje, jaké členy má čtečka mít: `pripona` a `nacti()`.
Čtečky z něj nemusí dědit; pro typovou kontrolu stačí odpovídající rozhraní.
JSON, XML a CSV čtou moduly standardní knihovny. TXT používá `klíč=hodnota`.
vCard má stejný omezený výukový profil jako C++ příklad: verze 3.0,
bez parametrů, skládání řádků a escape sekvencí. XML s DTD se odmítá.
Python JSON navíc zvládá standardní Unicode escape sekvence a CSV i víceřádková
pole v uvozovkách. Obě ukázky využívají stejná povinná textová pole kontaktu.

## Generika jako protějšek šablony

V `sablony/main.py` najdeš `Databaze(Generic[T])` a
`T = TypeVar("T", bound=Ctecka)`. Parametr `T` popisuje typ čtečky:

```python
from spolecne import Json

db: Databaze[Json] = Databaze(Json())
db.nacti(slozka)
db.zobraz()
```

**Python nemá C++ šablony.** Generika poskytují informace editoru a nástrojům
pro kontrolu typů; Python nevytváří pro každé `T` samostatnou přeloženou třídu.
Typové anotace samy nekontrolují hodnoty za běhu. Proto v programu samostatně
ověřujeme vstupní data. Skutečné chování určuje předaný objekt čtečky
(`Json()`, `Csv()` atd.). Tento způsob skládání objektů se nazývá kompozice.
Slovník `CTECKY` podle vstupu vybere třídu a zápis `CTECKY[typ]()` vytvoří objekt.

## Dědičnost

V `dedicnost/main.py` je společný základ `Databaze(ABC)`.
Dekorátor `@abstractmethod` označuje metodu, kterou musí konkrétní třídy
implementovat. Samotný abstraktní základ nelze vytvořit jako objekt.
`JsonDatabaze` a ostatní třídy dědí výpis i konstruktor a přepisují `nacti()`.
Slovník `TRIDY` vybírá konkrétní databázi. Následující volání `db.nacti()` má
stále stejný zápis, ale podle objektu používá jinou metodu: to je polymorfismus.
Python k tomu nepotřebuje klíčové slovo `virtual` ani C++ správu ukazatelů.

## Vyzkoušej

1. Přidej sedmý kontakt a porovnej Python a C++ výstup.
2. Vytvoř dvě databáze s různými čtečkami. Mají společný seznam `data`?
3. Přidej vyhledání podle části jména a použij ho pro všechny formáty.
4. Zkus vytvořit `Databaze()` z varianty s dědičností. Proč Python objekt odmítne?
5. Vysvětli, co u generické varianty zajistí anotace a co předaný objekt čtečky.
