"""Abstraktní databáze a pět konkrétních odvozených tříd."""
from abc import ABC, abstractmethod
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from spolecne import (Kontakt, Json, Xml, Csv, Txt, Vcard,
                     nacti_slozku, vstup, vypis)


class Databaze(ABC):
    def __init__(self) -> None:
        self.data: list[Kontakt] = []

    @abstractmethod
    def nacti(self, slozka: Path) -> None:
        """Odvozená třída musí tuto metodu implementovat."""

    def zobraz(self) -> None:
        vypis(self.data)


class JsonDatabaze(Databaze):
    def nacti(self, slozka: Path) -> None:
        self.data = nacti_slozku(slozka, Json())


class XmlDatabaze(Databaze):
    def nacti(self, slozka: Path) -> None:
        self.data = nacti_slozku(slozka, Xml())


class CsvDatabaze(Databaze):
    def nacti(self, slozka: Path) -> None:
        self.data = nacti_slozku(slozka, Csv())


class TxtDatabaze(Databaze):
    def nacti(self, slozka: Path) -> None:
        self.data = nacti_slozku(slozka, Txt())


class VcardDatabaze(Databaze):
    def nacti(self, slozka: Path) -> None:
        self.data = nacti_slozku(slozka, Vcard())


TRIDY: dict[str, type[Databaze]] = {
    "json": JsonDatabaze, "xml": XmlDatabaze, "csv": CsvDatabaze,
    "txt": TxtDatabaze, "vcard": VcardDatabaze,
}


def main() -> int:
    try:
        typ, slozka = vstup()
        db = TRIDY[typ]()  # Továrna vybere a vytvoří konkrétní databázi.
        db.nacti(slozka)   # Polymorfismus: stejný zápis volá různé implementace.
        db.zobraz()
        return 0
    except (ValueError, OSError, EOFError) as chyba:
        print(f"Chyba: {chyba}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
