"""Generická databáze: pythonový protějšek ukázky se šablonou."""
from pathlib import Path
import sys
from typing import Generic, TypeVar

# Umožní spouštět tento příklad přímo z libovolné pracovní složky.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from spolecne import CTECKY, Ctecka, Kontakt, nacti_slozku, vstup, vypis

T = TypeVar("T", bound=Ctecka)


class Databaze(Generic[T]):
    """T označuje typ čtečky pro typovou kontrolu, nevytváří nový strojový kód."""
    def __init__(self, ctecka: T) -> None:
        self.ctecka = ctecka
        self.data: list[Kontakt] = []  # Každý objekt má vlastní seznam kontaktů.

    def nacti(self, slozka: Path) -> None:
        self.data = nacti_slozku(slozka, self.ctecka)

    def zobraz(self) -> None:
        vypis(self.data)


def main() -> int:
    try:
        typ, slozka = vstup()
        # Slovník vybere třídu čtečky; závorky vytvoří její konkrétní objekt.
        db = Databaze(CTECKY[typ]())
        db.nacti(slozka)
        db.zobraz()
        return 0
    except (ValueError, OSError, EOFError) as chyba:
        print(f"Chyba: {chyba}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
