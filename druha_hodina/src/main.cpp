// Druha hodina: cteni a zpracovani radku ze seriove linky.
// Prikazy piste bez diakritiky a odesilejte klavesou Enter.
#include <Arduino.h>

const byte LED_PIN = LED_BUILTIN;
const unsigned int MAX_DELKA = 64;
String radek = "";
bool prilisDlouhy = false;
bool ledSviti = false;
bool predchoziBylCR = false;

void napoveda() {
  Serial.println(F("Prikazy: pomoc, zapni, vypni, stav, echo TEXT"));
}

void zpracujRadek(String prikaz) {
  // Automaticke echo potvrdi prijem i u prazdneho nebo neznameho prikazu.
  Serial.print(F("Prijato: ["));
  Serial.print(prikaz);
  Serial.println(F("]"));
  prikaz.trim();  // Odstrani mezery na zacatku a konci radku.
  if (prikaz.length() == 0) return;

  if (prikaz == "pomoc") {
    napoveda();
  } else if (prikaz == "zapni" || prikaz == "vypni") {
    ledSviti = (prikaz == "zapni");
    digitalWrite(LED_PIN, ledSviti ? HIGH : LOW);
    Serial.println(ledSviti ? F("LED zapnuta.") : F("LED vypnuta."));
  } else if (prikaz == "stav") {
    Serial.println(ledSviti ? F("LED sviti.") : F("LED nesviti."));
  } else if (prikaz.startsWith("echo ")) {
    Serial.print(F("Prijaty text: "));
    Serial.println(prikaz.substring(5));
  } else {
    Serial.print(F("Neznamy prikaz: "));
    Serial.println(prikaz);
    napoveda();
  }
}

void setup() {
  pinMode(LED_PIN, OUTPUT);
  digitalWrite(LED_PIN, LOW);
  Serial.begin(9600);
  radek.reserve(MAX_DELKA);
  Serial.println(F("Cteni seriove linky je pripraveno (9600 baud)."));
  napoveda();
}

void loop() {
  // available() zjisti, zda nejaky znak ceka; read() precte jeden znak.
  // Bez cekani na cely radek muze Arduino mezitim delat i jinou praci.
  while (Serial.available() > 0) {
    char znak = Serial.read();
    // Enter muze poslat CR, LF nebo CRLF. CRLF zpracujeme jen jednou.
    if (znak == '\n' && predchoziBylCR) {
      predchoziBylCR = false;
      continue;
    }
    predchoziBylCR = (znak == '\r');

    if (znak == '\n' || znak == '\r') {
      Serial.println();  // Ukonci okamzite echo zadavanych znaku.
      if (prilisDlouhy) {
        Serial.println(F("Chyba: radek ma vice nez 64 znaku. Posli kratsi."));
      } else {
        zpracujRadek(radek);
      }
      radek = "";
      prilisDlouhy = false;
    } else if (!prilisDlouhy) {
      // Echo kazdeho znaku funguje jeste pred Enterem.
      Serial.write(znak);
      if (radek.length() < MAX_DELKA) {
        radek += znak;
      } else {
        // Zbytek dlouheho radku zahodime, aby se nestal dalsim prikazem.
        prilisDlouhy = true;
      }
    }
  }
}
