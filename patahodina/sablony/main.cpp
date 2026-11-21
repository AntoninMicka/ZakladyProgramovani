#include "kontakty.hpp"
using namespace kontakty;

// Parametr šablony určí čtečku při překladu. Nevzniká virtuální volání.
// Pro každou použitou čtečku překladač vytvoří konkrétní typ databáze.
template<class Ctecka>
class Databaze {
    std::vector<Kontakt> data; // Soukromý stav: každý objekt má vlastní kontakty.
public: // Metody dostupné z hlavního programu.
    void nacti(const fs::path& slozka) { data = nacti_slozku<Ctecka>(slozka); }
    void zobraz() const { vypis(data); }
};
template<class Ctecka>
void spust(const fs::path& slozka) {
    Databaze<Ctecka> db; // Lokální objekt se po skončení funkce automaticky zruší.
    db.nacti(slozka);
    db.zobraz();
}
int main(int argc, char** argv) {
    try {
        auto [typ,slozka]=vstup(argc,argv); // Ověření typu a určení cesty k datům.
        // Uživatelský vstup vybírá jednu z již přeložených instancí šablony.
        if(typ=="xml") spust<Xml>(slozka);
        else if(typ=="json") spust<Json>(slozka);
        else if(typ=="vcard") spust<Vcard>(slozka);
        else if(typ=="csv") spust<Csv>(slozka);
        else spust<Txt>(slozka);
    // Chybu čtení oznámíme uživateli a vrátíme nenulový návratový kód.
    } catch(const std::exception& e) { std::cerr << "Chyba: " << e.what() << '\n'; return 1; }
}
