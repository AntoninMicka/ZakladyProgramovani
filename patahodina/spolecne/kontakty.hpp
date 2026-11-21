#pragma once
#include <algorithm>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <map>
#include <memory>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>
#include <libxml/parser.h>

namespace kontakty {
namespace fs = std::filesystem;
// Jeden společný datový typ pro všechny formáty; řetězce vlastní své hodnoty.
struct Kontakt { std::string jmeno, email, telefon; };
using Pole = std::map<std::string, std::string>;
// Převod pojmenovaných polí na kontakt včetně kontroly povinných údajů.
inline Kontakt kontakt(const Pole& p) {
    for (auto k : {"jmeno", "email", "telefon"})
        if (!p.count(k) || p.at(k).empty()) throw std::runtime_error(std::string("Chybí pole: ") + k);
    return {p.at("jmeno"), p.at("email"), p.at("telefon")};
}
// Duplicitní klíč nesmí potichu přepsat již načtenou hodnotu.
inline void uloz(Pole& p, const std::string& k, const std::string& v) {
    if (!p.emplace(k,v).second) throw std::runtime_error("Duplicitní pole: " + k);
}
// Společné čtení textového souboru pro všechny čtečky.
inline std::string obsah(const fs::path& cesta) {
    std::ifstream f(cesta, std::ios::binary);
    if (!f) throw std::runtime_error("Nelze otevřít soubor");
    std::ostringstream s; s << f.rdbuf();
    if (f.bad()) throw std::runtime_error("Chyba čtení");
    return s.str();
}
// Záměrně malý JSON profil: objekt s textovými hodnotami v UTF-8.
// Nepodporované struktury a escape sekvence odmítáme, nesnažíme se je odhadnout.
inline std::string json_text(std::istream& in) {
    in >> std::ws;
    if (in.get() != '"') throw std::runtime_error("JSON: očekáván řetězec");
    std::string s; char c;
    while (in.get(c)) {
        if (c == '"') return s;
        if (static_cast<unsigned char>(c) < 32) throw std::runtime_error("JSON: řídicí znak");
        if (c == '\\') {
            if (!in.get(c)) break;
            switch(c) {
                case '"': case '\\': case '/': break;
                case 'n': c='\n'; break; case 'r': c='\r'; break;
                case 't': c='\t'; break; case 'b': c='\b'; break; case 'f': c='\f'; break;
                default: throw std::runtime_error("JSON: nepodporovaný escape (použij UTF-8)");
            }
        }
        s += c;
    }
    throw std::runtime_error("JSON: neukončený řetězec");
}
// Čtečka JSON: stejné rozhraní pripona + nacti jako u ostatních formátů.
struct Json {
    static constexpr const char* pripona = ".json";
    static Kontakt nacti(const fs::path& cesta) {
        std::istringstream in(obsah(cesta)); Pole p; char c;
        in >> c; if (c!='{') throw std::runtime_error("JSON: očekáváno {");
        do {
            auto k=json_text(in); in >> c;
            if(c!=':') throw std::runtime_error("JSON: očekáváno :");
            auto v=json_text(in); uloz(p,k,v); in >> c;
        } while(in && c==',');
        if(!in || c!='}') throw std::runtime_error("JSON: očekáváno }");
        in >> std::ws; if(!in.eof()) throw std::runtime_error("JSON: data za objektem");
        return kontakt(p);
    }
};
// Čtečka XML svěřuje syntaxi dokumentu knihovně libxml2.
struct Xml {
    static constexpr const char* pripona = ".xml";
    static Kontakt nacti(const fs::path& cesta) {
        // Bez expanze entit a přístupu k síti; DTD do výukového formátu nepatří.
        auto text=obsah(cesta);
        std::unique_ptr<xmlDoc, decltype(&xmlFreeDoc)> doc(
            xmlReadMemory(text.data(), static_cast<int>(text.size()), "kontakt.xml", nullptr,
                          XML_PARSE_NONET | XML_PARSE_NOERROR | XML_PARSE_NOWARNING), xmlFreeDoc);
        if(!doc || doc->intSubset || doc->extSubset) throw std::runtime_error("XML: neplatný dokument nebo DTD");
        auto root=xmlDocGetRootElement(doc.get());
        if(!root || xmlStrcmp(root->name, BAD_CAST "kontakt")) throw std::runtime_error("XML: očekáván kontakt");
        Pole p;
        for(auto n=root->children; n; n=n->next) if(n->type==XML_ELEMENT_NODE) {
            auto value=xmlNodeGetContent(n);
            std::string v=value ? reinterpret_cast<const char*>(value) : "";
            xmlFree(value); uloz(p,reinterpret_cast<const char*>(n->name),v);
        }
        return kontakt(p);
    }
};
// CSV podporuje uvozovky, čárky uvnitř pole a zdvojené uvozovky.
// Jeden záznam musí být na jednom řádku.
inline std::vector<std::string> csv_radek(const std::string& s) {
    std::vector<std::string> out; size_t i=0;
    while(true) {
        std::string v;
        if(i<s.size() && s[i]=='"') {
            ++i; bool konec=false;
            while(i<s.size()) {
                char c=s[i++];
                if(c=='"') {
                    if(i<s.size() && s[i]=='"') ++i;
                    else { konec=true; break; }
                }
                v+=c;
            }
            if(!konec) throw std::runtime_error("CSV: neukončené uvozovky");
        } else {
            while(i<s.size() && s[i]!=',') {
                if(s[i]=='"') throw std::runtime_error("CSV: neočekávané uvozovky");
                v+=s[i++];
            }
        }
        out.push_back(v);
        if(i==s.size()) return out;
        if(s[i++]!=',') throw std::runtime_error("CSV: očekávána čárka");
    }
}
inline std::vector<std::string> radky(const fs::path& cesta) {
    std::istringstream in(obsah(cesta)); std::vector<std::string> out; std::string s;
    while(std::getline(in,s)) {
        if(!s.empty() && s.back()=='\r') s.pop_back();
        out.push_back(s);
    }
    return out;
}
// Čtečka CSV propojí názvy sloupců s hodnotami jediného kontaktu.
struct Csv {
    static constexpr const char* pripona = ".csv";
    static Kontakt nacti(const fs::path& cesta) {
        auto r=radky(cesta);
        if(r.size()!=2) throw std::runtime_error("CSV: očekávána hlavička a jeden kontakt");
        auto k=csv_radek(r[0]), v=csv_radek(r[1]); Pole p;
        if(k.size()!=3 || v.size()!=3) throw std::runtime_error("CSV: očekávány tři sloupce");
        for(size_t i=0;i<k.size();++i) uloz(p,k[i],v[i]);
        return kontakt(p);
    }
};
// Čtečka TXT rozděluje každý řádek na klíč a hodnotu podle prvního =.
struct Txt {
    static constexpr const char* pripona = ".txt";
    static Kontakt nacti(const fs::path& cesta) {
        Pole p;
        for(const auto& r:radky(cesta)) {
            auto i=r.find('=');
            if(i==std::string::npos) throw std::runtime_error("TXT: očekáváno klíč=hodnota");
            uloz(p,r.substr(0,i),r.substr(i+1));
        }
        return kontakt(p);
    }
};
// Čtečka vCard mapuje standardní FN, EMAIL a TEL na společná pole.
struct Vcard {
    static constexpr const char* pripona = ".vcf";
    static Kontakt nacti(const fs::path& cesta) {
        auto r=radky(cesta); Pole p;
        if(r.size()<3 || r.front()!="BEGIN:VCARD" || r.back()!="END:VCARD")
            throw std::runtime_error("vCard: chybné ohraničení");
        for(size_t i=1;i+1<r.size();++i) {
            auto pos=r[i].find(':');
            if(pos==std::string::npos) throw std::runtime_error("vCard: chybí dvojtečka");
            uloz(p,r[i].substr(0,pos),r[i].substr(pos+1));
        }
        if(p["VERSION"]!="3.0") throw std::runtime_error("vCard: očekávána verze 3.0");
        // Výukový profil bez skládání řádků, parametrů a escape sekvencí.
        for(auto key:{"FN","EMAIL","TEL"}) if(p[key].find('\\')!=std::string::npos)
            throw std::runtime_error("vCard: escape sekvence nejsou v tomto profilu podporovány");
        return kontakt({{"jmeno",p["FN"]},{"email",p["EMAIL"]},{"telefon",p["TEL"]}});
    }
};
// Sdílený algoritmus: obě varianty používají stejné pořadí a chybové hlášení.
// Načítání je transakční: při chybě nevypisujeme neúplnou databázi.
template<class Ctecka>
std::vector<Kontakt> nacti_slozku(const fs::path& slozka) {
    std::vector<fs::path> soubory;
    for(const auto& e:fs::directory_iterator(slozka))
        if(e.is_regular_file() && e.path().extension()==Ctecka::pripona) soubory.push_back(e.path());
    std::sort(soubory.begin(),soubory.end());
    if(soubory.empty()) throw std::runtime_error("Složka neobsahuje podporované soubory: " + slozka.string());
    std::vector<Kontakt> data;
    for(const auto& f:soubory) {
        try { data.push_back(Ctecka::nacti(f)); }
        catch(const std::exception& e) { throw std::runtime_error(f.string()+": "+e.what()); }
    }
    return data;
}
inline void vypis(const std::vector<Kontakt>& data) {
    std::cout << "Načteno kontaktů: " << data.size() << '\n';
    for(const auto& k:data) std::cout << k.jmeno << " | " << k.email << " | " << k.telefon << '\n';
}
// Typ se zadá argumentem nebo otázkou na začátku běhu.
inline std::pair<std::string, fs::path> vstup(int argc, char** argv) {
    if(argc>3) throw std::runtime_error("Použití: program [xml|json|vcard|csv|txt] [složka kontaktů]");
    std::string typ;
    if(argc>1) typ=argv[1];
    else { std::cout << "Formát (xml/json/vcard/csv/txt): " << std::flush; std::getline(std::cin,typ); }
    if(typ!="xml" && typ!="json" && typ!="vcard" && typ!="csv" && typ!="txt")
        throw std::runtime_error("Nepodporovaný formát: " + typ);
    return {typ, argc>2 ? fs::path(argv[2]) : fs::path(KONTAKTY_DIR)/typ};
}
} // namespace kontakty
