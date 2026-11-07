/* Spustitelný průvodce syntaxí C17, bez vstupu z klávesnice.
 * Překlad: gcc -std=c17 -Wall -Wextra -Wpedantic zaklady_c.c -o zaklady_c
 * Spuštění: ./zaklady_c
 */
#include <stdbool.h>  // bool, true, false
#include <stdio.h>    // printf, puts, snprintf
#include <stdlib.h>   // strtol
#include <errno.h>    // errno, ERANGE

/* 7. FUNKCE: typy parametrů i výsledku jsou povinné.
 * C nemá výchozí argumenty. Text vracíme přes pole předané volajícím.
 * snprintf omezuje zápis velikostí pole (včetně ukončovacího znaku '\0').
 */
void pozdrav(char *vysledek, size_t kapacita,
             const char *osoba, const char *osloveni) {
    snprintf(vysledek, kapacita, "%s, %s!", osloveni, osoba);
}

int main(void) {
    // 1. KOMENTÁŘE, PROMĚNNÉ A TYPY
    // Komentář je // nebo /* ... */. Příkaz obvykle končí středníkem.
    const char *jmeno = "Eva";  // Ukazatel na text, který zde neměníme.
    int vek = 20;
    double vyska = 1.72;
    bool je_student = true;
    const char *prezdivka = NULL;  // NULL: ukazatel neodkazuje na hodnotu.
    puts("1. Proměnné a typy");
    // %s text, %d int, %.2f desetinné číslo se dvěma místy.
    printf("%s má %d let a měří %.2f m.\n", jmeno, vek, vyska);
    // NULL nesmíme předat %s; nejprve vybereme náhradní text.
    printf("Student: %s, přezdívka: %s\n", je_student ? "ano" : "ne",
           prezdivka != NULL ? prezdivka : "neuvedena");

    // 2. OPERÁTORY
    // Dělení dvou int je celočíselné. S double dostaneme desetinný výsledek.
    // C nemá operátor **; ^ znamená bitový XOR, nikoli mocninu!
    puts("\n2. Operátory");
    printf("7 + 2 = %d, 7.0 / 2 = %.1f, 7 / 2 = %d\n", 7 + 2, 7.0 / 2, 7 / 2);
    printf("7 %% 2 = %d, 2 * 2 * 2 = %d\n", 7 % 2, 2 * 2 * 2);
    // U záporných čísel C dělí směrem k nule, Python // směrem dolů.

    // 3. PODMÍNKY A BLOKY
    // Blok tvoří { }, odsazení pomáhá čtenáři. && je „a“, || „nebo“, ! „ne“.
    // == porovnává, = přiřazuje. Dále: !=, <, <=, >, >=.
    puts("\n3. Podmínky");
    if (vek >= 18 && je_student) {
        puts("Jsi dospělý student.");
    } else if (vek >= 18) {
        puts("Jsi dospělý.");
    } else {
        puts("Ještě ti nebylo 18 let.");
    }

    // 4. POLE A FOR
    // Pole má pevnou kapacitu. Nemá append ani záporné indexy či výřezy.
    // Zvlášť sledujeme počet použitých prvků. Indexy začínají nulou.
    puts("\n4. Pole a cyklus for");
    const char *ovoce[4] = {"jablko", "hruška", "švestka"};
    size_t pocet = 3;  // size_t je typ pro velikosti a indexy; tiskne se %zu.
    ovoce[pocet] = "meruňka";  // Volné místo je zde zajištěné kapacitou 4.
    pocet++;
    printf("První: %s, poslední: %s, počet: %zu\n", ovoce[0], ovoce[pocet - 1], pocet);
    printf("První dvě položky: %s, %s\n", ovoce[0], ovoce[1]);
    for (size_t i = 0; i < pocet; i++) {
        printf("%zu. %s\n", i + 1, ovoce[i]);
    }
    for (int cislo = 1; cislo < 4; cislo++) {
        printf("%d na druhou = %d\n", cislo, cislo * cislo);
    }

    // 5. WHILE, CONTINUE A BREAK
    puts("\n5. Cyklus while");
    int pocitadlo = 0;
    while (pocitadlo < 5) {
        pocitadlo += 1;
        if (pocitadlo == 2) continue;
        if (pocitadlo == 4) break;
        printf("%d\n", pocitadlo);  // Vypíše 1 a 3.
    }

    // 6. STRUKTURY A JEDINEČNÉ PRVKY
    // C nemá vestavěný slovník, n-tici ani množinu jako Python.
    // Pro známá pojmenovaná pole použijeme struct (není to obecný slovník).
    puts("\n6. Struktury a kolekce");
    struct Student { const char *jmeno; int vek; const char *obor; };
    struct Student student = {jmeno, vek, "informatika"};
    printf("jmeno: %s\nvek: %d\nobor: %s\n", student.jmeno, student.vek, student.obor);
    const struct Bod { int x; int y; } souradnice = {10, 20};
    printf("Souřadnice: x=%d, y=%d\n", souradnice.x, souradnice.y);
    int cisla[] = {1, 2, 2, 3};
    int unikatni[4];
    size_t pocet_unikatnich = 0;
    for (size_t i = 0; i < sizeof cisla / sizeof cisla[0]; i++) {
        bool nalezeno = false;
        for (size_t j = 0; j < pocet_unikatnich; j++) {
            if (unikatni[j] == cisla[i]) nalezeno = true;
        }
        if (!nalezeno) unikatni[pocet_unikatnich++] = cisla[i];
    }
    bool obsahuje_dvojku = false;
    printf("Jedinečná čísla:");
    for (size_t i = 0; i < pocet_unikatnich; i++) {
        printf(" %d", unikatni[i]);
        if (unikatni[i] == 2) obsahuje_dvojku = true;
    }
    printf("\nJe číslo 2 mezi prvky? %s\n", obsahuje_dvojku ? "ano" : "ne");

    puts("\n7. Funkce");
    char zprava[100];
    pozdrav(zprava, sizeof zprava, jmeno, "Ahoj");
    puts(zprava);
    pozdrav(zprava, sizeof zprava, "Petře", "Dobrý den");
    puts(zprava);

    // 8. PŘEVODY A CHYBY
    // C nemá try/except. Kontrolujeme návratové hodnoty a chybové příznaky.
    // strtol převede text na long; konec ukáže první nepřevedený znak.
    puts("\n8. Zpracování chyby");
    const char *texty[] = {"42", "ahoj"};
    for (size_t i = 0; i < 2; i++) {
        char *konec;
        errno = 0;
        long cislo = strtol(texty[i], &konec, 10);
        if (konec == texty[i] || *konec != '\0' || errno == ERANGE) {
            printf("Text '%s' nelze převést na celé číslo typu long.\n", texty[i]);
        } else {
            printf("Převod se podařil: %ld\n", cislo);
        }
    }

    // 9. NÁHRADA SEZNAMOVÉ KOMPREHENZE: cyklus, podmínka a pole.
    puts("\n9. Druhé mocniny sudých čísel");
    int ctverce_sudych[3];
    size_t pocet_ctvercu = 0;
    for (int n = 1; n <= 6; n++) {
        if (n % 2 == 0) ctverce_sudych[pocet_ctvercu++] = n * n;
    }
    for (size_t i = 0; i < pocet_ctvercu; i++) printf("%d ", ctverce_sudych[i]);
    puts("");

    // VLASTNÍ POKUSY: změň věk, přidej ovoce (i kapacitu pole), zavolej pozdrav.
    // Volitelný vstup textu: char vstup[80]; fgets(vstup, sizeof vstup, stdin);
    // Vždy ověř návrat fgets; text může obsahovat koncové '\n'.
    return 0;  // Nula znamená úspěšné ukončení programu.
}
