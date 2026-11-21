"""Společný model a čtečky. Pouze standardní knihovna Pythonu 3.10+."""
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
import argparse
import csv
import json
import xml.etree.ElementTree as ET


@dataclass(frozen=True)
class Kontakt:
    """Jeden objekt kontaktu; atributy jsou nezávislé na formátu souboru."""
    jmeno: str
    email: str
    telefon: str


def kontakt(pole: dict) -> Kontakt:
    for klic in ("jmeno", "email", "telefon"):
        if not isinstance(pole.get(klic), str) or not pole[klic].strip():
            raise ValueError(f"Chybí neprázdné textové pole: {klic}")
    return Kontakt(pole["jmeno"], pole["email"], pole["telefon"])


def uloz(pole: dict, klic: str, hodnota: str) -> None:
    if klic in pole:
        raise ValueError(f"Duplicitní pole: {klic}")
    pole[klic] = hodnota


def json_pole(dvojice: list) -> dict:
    pole: dict = {}
    for klic, hodnota in dvojice:
        uloz(pole, klic, hodnota)
    return pole


class Ctecka(Protocol):
    """Typový kontrakt: čtečka nabízí příponu a metodu nacti()."""
    pripona: str

    def nacti(self, cesta: Path) -> Kontakt: ...


class Json:
    pripona = ".json"

    def nacti(self, cesta: Path) -> Kontakt:
        pole = json.loads(cesta.read_text(encoding="utf-8"), object_pairs_hook=json_pole)
        if not isinstance(pole, dict):
            raise ValueError("JSON: očekáván objekt")
        return kontakt(pole)


class Xml:
    pripona = ".xml"

    def nacti(self, cesta: Path) -> Kontakt:
        text = cesta.read_text(encoding="utf-8")
        if "<!DOCTYPE" in text:
            raise ValueError("XML: DTD není podporováno")
        root = ET.fromstring(text)
        if root.tag != "kontakt":
            raise ValueError("XML: očekáván kořen kontakt")
        pole: dict = {}
        for prvek in root:
            if len(prvek):
                raise ValueError("XML: očekáváno jednoduché textové pole")
            uloz(pole, prvek.tag, prvek.text or "")
        return kontakt(pole)


class Csv:
    pripona = ".csv"

    def nacti(self, cesta: Path) -> Kontakt:
        # newline='' dovolí modulu csv správně zpracovat konce řádků i uvozovky.
        with cesta.open(encoding="utf-8", newline="") as soubor:
            radky = list(csv.reader(soubor, strict=True))
        if len(radky) != 2 or len(radky[0]) != 3 or len(radky[1]) != 3:
            raise ValueError("CSV: očekávána hlavička a jeden kontakt se třemi sloupci")
        return kontakt(json_pole(list(zip(radky[0], radky[1]))))


class Txt:
    pripona = ".txt"

    def nacti(self, cesta: Path) -> Kontakt:
        pole: dict = {}
        for radek in cesta.read_text(encoding="utf-8").splitlines():
            klic, oddelovac, hodnota = radek.partition("=")
            if not oddelovac:
                raise ValueError("TXT: očekáváno klíč=hodnota")
            uloz(pole, klic, hodnota)
        return kontakt(pole)


class Vcard:
    """Základní profil vCard 3.0, stejná omezení jako v C++ ukázce."""
    pripona = ".vcf"

    def nacti(self, cesta: Path) -> Kontakt:
        radky = cesta.read_text(encoding="utf-8").splitlines()
        if len(radky) < 3 or radky[0] != "BEGIN:VCARD" or radky[-1] != "END:VCARD":
            raise ValueError("vCard: chybné ohraničení")
        pole: dict = {}
        for radek in radky[1:-1]:
            klic, oddelovac, hodnota = radek.partition(":")
            if not oddelovac:
                raise ValueError("vCard: chybí dvojtečka")
            uloz(pole, klic, hodnota)
        if pole.get("VERSION") != "3.0":
            raise ValueError("vCard: očekávána verze 3.0")
        if any("\\" in pole.get(k, "") for k in ("FN", "EMAIL", "TEL")):
            raise ValueError("vCard: escape sekvence nejsou podporovány")
        return kontakt({"jmeno": pole.get("FN"), "email": pole.get("EMAIL"),
                        "telefon": pole.get("TEL")})


CTECKY: dict[str, type[Ctecka]] = {
    "xml": Xml, "json": Json, "vcard": Vcard, "csv": Csv, "txt": Txt,
}


def nacti_slozku(slozka: Path, ctecka: Ctecka) -> list[Kontakt]:
    """Jeden algoritmus pro všechny formáty a obě varianty databáze."""
    soubory = sorted(p for p in slozka.iterdir()
                     if p.is_file() and p.suffix == ctecka.pripona)
    if not soubory:
        raise ValueError(f"Složka neobsahuje podporované soubory: {slozka}")
    data = []
    for cesta in soubory:
        try:
            data.append(ctecka.nacti(cesta))
        except (ValueError, OSError, ET.ParseError, csv.Error) as chyba:
            raise ValueError(f"{cesta}: {chyba}") from chyba
    return data


def vypis(data: list[Kontakt]) -> None:
    print(f"Načteno kontaktů: {len(data)}")
    for k in data:
        print(f"{k.jmeno} | {k.email} | {k.telefon}")


def vstup() -> tuple[str, Path]:
    parser = argparse.ArgumentParser(description="Databáze kontaktů v Pythonu")
    parser.add_argument("typ", nargs="?", choices=CTECKY)
    parser.add_argument("slozka", nargs="?", type=Path)
    args = parser.parse_args()
    typ = args.typ or input("Formát (xml/json/vcard/csv/txt): ").strip()
    if typ not in CTECKY:
        raise ValueError(f"Nepodporovaný formát: {typ}")
    # Cesta vychází z umístění zdrojového souboru, ne z pracovní složky.
    return typ, args.slozka if args.slozka is not None else Path(__file__).resolve().parents[1] / "kontakty" / typ
