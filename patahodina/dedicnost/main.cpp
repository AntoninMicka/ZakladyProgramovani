#include "kontakty.hpp"
using namespace kontakty;

// Abstraktní základ definuje společné rozhraní a vlastní data.
class Databaze {
protected: // Ke kontaktům mají přístup i odvozené třídy.
    std::vector<Kontakt> data;
public:
    virtual ~Databaze() = default; // Nutné pro mazání přes ukazatel na základ.
    virtual void nacti(const fs::path& slozka) = 0; // Čistě virtuální metoda: základ je abstraktní.
    void zobraz() const { vypis(data); }
};
// Koncové třídy lze používat všude, kde je očekávána Databaze.
// final zakazuje další dědění; override kontroluje přepsání metody základu.
class XmlDatabaze final : public Databaze {
    void nacti(const fs::path& s) override { data=nacti_slozku<Xml>(s); }
};
class JsonDatabaze final : public Databaze {
    void nacti(const fs::path& s) override { data=nacti_slozku<Json>(s); }
};
class VcardDatabaze final : public Databaze {
    void nacti(const fs::path& s) override { data=nacti_slozku<Vcard>(s); }
};
class CsvDatabaze final : public Databaze {
    void nacti(const fs::path& s) override { data=nacti_slozku<Csv>(s); }
};
class TxtDatabaze final : public Databaze {
    void nacti(const fs::path& s) override { data=nacti_slozku<Txt>(s); }
};
// Továrna vytvoří objekt vybraného typu a předá jeho vlastnictví volajícímu.
std::unique_ptr<Databaze> vytvor(const std::string& typ) {
    if(typ=="xml") return std::make_unique<XmlDatabaze>();
    if(typ=="json") return std::make_unique<JsonDatabaze>();
    if(typ=="vcard") return std::make_unique<VcardDatabaze>();
    if(typ=="csv") return std::make_unique<CsvDatabaze>();
    return std::make_unique<TxtDatabaze>();
}
int main(int argc, char** argv) {
    try {
        auto [typ,slozka]=vstup(argc,argv); // Neznámý formát se zde odmítne.
        auto db=vytvor(typ); // unique_ptr objekt automaticky zruší, i při výjimce.
        // Virtuální metoda se zvolí za běhu podle skutečného typu objektu.
        db->nacti(slozka);
        db->zobraz();
    // Stejné hlášení chyb jako ve variantě se šablonou.
    } catch(const std::exception& e) { std::cerr << "Chyba: " << e.what() << '\n'; return 1; }
}
