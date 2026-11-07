/* ÚKOL: Čtení a zápis textových souborů v C.
 * Doplň rozdělení čísel ze vstup.txt do sude.txt a liche.txt.
 * Zachovej pořadí a opakování, zapisuj jedno číslo na řádek.
 * Nula je sudá, záporná čísla posuzuj pomocí cislo % 2 == 0.
 *
 * Překlad: gcc -std=c17 -Wall -Wextra -Wpedantic ukol_soubory.c -o ukol_soubory
 * Spuštění: ./ukol_soubory (z adresáře s vstup.txt).
 * POZOR: spuštění vytvoří nebo přepíše oba výstupy!
 * Do doplnění úkolu zůstanou oba výstupy prázdné.
 */
#include <stdio.h>
#include <stdlib.h>
#include <errno.h>
#include <ctype.h>

int main(void) {
    // Standardní C hledá relativní cesty v pracovním adresáři, ne vedle zdroje.
    FILE *vstup = fopen("vstup.txt", "r");
    if (vstup == NULL) {
        perror("Nelze otevřít vstup.txt");
        return 1;
    }
    FILE *sude = fopen("sude.txt", "w");
    if (sude == NULL) {
        perror("Nelze otevřít sude.txt");
        fclose(vstup);
        return 1;
    }
    FILE *liche = fopen("liche.txt", "w");
    if (liche == NULL) {
        perror("Nelze otevřít liche.txt");
        fclose(sude);
        fclose(vstup);
        return 1;
    }

    char radek[128];
    size_t pocet_radku = 0;
    int chyba = 0;
    // fgets načte nejvýše sizeof radek - 1 bajtů a přidá '\0'.
    while (fgets(radek, sizeof radek, vstup) != NULL) {
        pocet_radku++;
        // Vstup obsahuje krátké řádky; dlouhé řádky odmítneme celé.
        size_t delka = 0;
        while (radek[delka] != '\0') delka++;
        if (delka == sizeof radek - 1 && radek[delka - 1] != '\n') {
            fprintf(stderr, "Řádek %zu je příliš dlouhý.\n", pocet_radku);
            chyba = 1;
            break;
        }
        char *konec;
        errno = 0;
        long cislo = strtol(radek, &konec, 10);
        int neplatne = (konec == radek || errno == ERANGE);
        while (isspace((unsigned char)*konec)) konec++;
        if (neplatne || *konec != '\0') {
            fprintf(stderr, "Neplatné číslo na řádku %zu.\n", pocet_radku);
            chyba = 1;
            break;
        }

        // TODO: pomocí if a cislo % 2 rozhodni, do kterého souboru zapsat.
        // Nápověda: fprintf(sude, "%ld\n", cislo); obdobně pro liche.
        // Záporná návratová hodnota fprintf znamená chybu zápisu.
        (void)cislo;  // Až proměnnou použiješ, tento řádek můžeš odstranit.
    }
    if (ferror(vstup)) {
        perror("Chyba čtení vstupu");
        chyba = 1;
    }
    // C nemá Pythoní with: každý otevřený soubor musíme zavřít.
    if (fclose(vstup) != 0) chyba = 1;
    if (fclose(sude) != 0) { perror("Chyba zavření sude.txt"); chyba = 1; }
    if (fclose(liche) != 0) { perror("Chyba zavření liche.txt"); chyba = 1; }
    if (chyba) return 1;
    printf("Načteno %zu řádků ze souboru vstup.txt.\n", pocet_radku);
    puts("Soubory sude.txt a liche.txt byly vytvořeny. Doplň jejich naplnění.");
    return 0;
}
