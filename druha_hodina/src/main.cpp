/* Arduino je platforma pro tvorbu elektronickych projektu. Program bezi
 * v mikrokontroleru na desce a muze cist vstupy (napr. tlacitka nebo senzory)
 * a ovladat vystupy (napr. LED nebo motory pres vhodne zapojeni).
 * Tento projekt pouziva Arduino Uno s mikrokontrolerem ATmega328P,
 * ktere ve Wokwi simulujeme. Program piseme v C++ s knihovnami Arduino:
 * setup() pripravi desku a loop() opakovane vykonava hlavni cinnost.
 * Seriova linka zde slouzi k prijmu prikazu z pocitace a odesilani odpovedi.
 */

// Druha hodina: cteni a zpracovani radku ze seriove linky.
// Prikazy piste bez diakritiky a odesilejte klavesou Enter.
#include <Arduino.h>
#include <avr/interrupt.h>  // ISR() a vektor preruseni ADC_vect pro ATmega328P.
#include <util/atomic.h>    // ATOMIC_BLOCK: bezpecne sdileni dat s prerusenim.

/* Strucne popisy vychazeji z oficialni dokumentace Arduino:
 * Serial (begin, available, read, print, println, write):
 * https://docs.arduino.cc/language-reference/en/functions/communication/serial/
 * String (length, trim, startsWith, substring, reserve):
 * https://docs.arduino.cc/language-reference/en/variables/data-types/stringObject/
 * Rizeni pinu:
 * https://docs.arduino.cc/language-reference/en/functions/digital-io/pinmode/
 * https://docs.arduino.cc/language-reference/en/functions/digital-io/digitalwrite/
 * Zivotni cyklus programu (setup, loop):
 * https://docs.arduino.cc/language-reference/en/structure/sketch/setup/
 * https://docs.arduino.cc/language-reference/en/structure/sketch/loop/
 */

const byte LED_PIN = LED_BUILTIN;
const unsigned int MAX_DELKA = 64;
String radek = "";
bool prilisDlouhy = false;
bool ledSviti = false;
bool predchoziBylCR = false;

const byte MOTOR_STEP_PIN = 2;
const byte MOTOR_DIR_PIN = 3;
const int KROKU_PUL_OTACKY = 100;  // Motor ma 200 plnych kroku na otacku.
const unsigned long INTERVAL_KROKU_US = 10000;  // Nejvyse 100 kroku/s.
int polohaMotoru = 0;  // Ve Wokwi pocatecni poloha 0 odpovida 12 hodinam.
int cilMotoru = 0;
unsigned long posledniKrokUs = 0;
bool krokVysoky = false;

void pripravMotor() {
  pinMode(MOTOR_STEP_PIN, OUTPUT);
  pinMode(MOTOR_DIR_PIN, OUTPUT);
  digitalWrite(MOTOR_STEP_PIN, LOW);
  digitalWrite(MOTOR_DIR_PIN, HIGH);  // A4988: HIGH = po smeru hodin.
}

// A4988 provede krok na nabezne hrane STEP. Impulzy generujeme bez cekani.
// Zdroj: https://docs.wokwi.com/parts/wokwi-a4988
void obsluzMotor() {
  // micros() vraci mikrosekundy od startu, rozdil snese i preteceni casovace.
  unsigned long ted = micros();
  if (krokVysoky) {
    if (ted - posledniKrokUs >= 4) {  // STEP nechame HIGH alespon 4 us.
      digitalWrite(MOTOR_STEP_PIN, LOW);
      krokVysoky = false;
    }
    return;
  }
  if (polohaMotoru == cilMotoru || ted - posledniKrokUs < INTERVAL_KROKU_US) return;

  bool poSmeru = cilMotoru > polohaMotoru;
  digitalWrite(MOTOR_DIR_PIN, poSmeru ? HIGH : LOW);
  // DIR musi byt stabilni pred hranou STEP; kratka 1 us pauza splni predstih.
  delayMicroseconds(1);
  digitalWrite(MOTOR_STEP_PIN, HIGH);
  posledniKrokUs = micros();
  krokVysoky = true;
  polohaMotoru += poSmeru ? 1 : -1;
}

const unsigned long INTERVAL_ADC_MS = 1000;
unsigned long posledniPrevodMs = 0;
// volatile upozornuje prekladac, ze hodnoty meni i obsluha preruseni.
volatile uint16_t vysledekADC = 0;
volatile bool adcPripraven = false;

// Hardware tuto obsluhu vyvola po dokonceni kazdeho spusteneho prevodu.
// ADC je 10bitovy vysledek (0 az 1023); cteni zajisti poradi ADCL, pak ADCH.
// V ISR nevypisujeme na Serial ani necekame: pouze predame data hlavni smycce.
ISR(ADC_vect) {
  vysledekADC = ADC;
  adcPripraven = true;
}

// Nastaveni registru plati pro Arduino Uno s ATmega328P.
// Zdroj: Microchip, ATmega328P datasheet, kapitola Analog-to-Digital Converter:
// https://ww1.microchip.com/downloads/en/DeviceDoc/Atmel-7810-Automotive-Microcontrollers-ATmega328P_Datasheet.pdf
void pripravADC() {
  ADCSRA = 0;  // Pri konfiguraci vypneme prevodnik a jeho preruseni.
  ADMUX = _BV(REFS0);  // Reference AVcc (na Unu 5 V), kanal ADC0 = pin A0.
  ADCSRB = 0;  // Nepouzivame automaticke spousteni prevodu.
  DIDR0 |= _BV(ADC0D);  // Vypneme nepotrebny digitalni vstupni buffer na A0.
  // ADEN zapne ADC, ADIE povoli preruseni, ADIF=1 smaze stary priznak.
  // Delicka 128: z 16 MHz vznikne takt ADC 125 kHz.
  ADCSRA = _BV(ADEN) | _BV(ADIE) | _BV(ADIF)
          | _BV(ADPS2) | _BV(ADPS1) | _BV(ADPS0);
  ADCSRA |= _BV(ADSC);  // ADSC spusti prvni prevod; na vysledek necekame.
  posledniPrevodMs = millis();
}

void obsluzADC() {
  uint16_t hodnota = 0;
  bool noveMereni = false;
  // Uno je 8bitove: cteni 16bitove hodnoty musi byt chranene pred ISR.
  // Blok docasne zakaze preruseni a pak obnovi jejich puvodni stav.
  ATOMIC_BLOCK(ATOMIC_RESTORESTATE) {
    if (adcPripraven) {
      hodnota = vysledekADC;
      adcPripraven = false;
      noveMereni = true;
    }
  }
  if (noveMereni) {
    // Rozsah ADC 0..1023 prevedeme na 0..100 kroku, tj. uhel 0..180 stupnu.
    // Nasobime jako unsigned long, aby na 16bitovem AVR nepreteklo mezicislo.
    cilMotoru = (static_cast<unsigned long>(hodnota) * KROKU_PUL_OTACKY + 511UL) / 1023UL;
    Serial.print(F("ADC A0: "));
    Serial.print(hodnota);
    Serial.print(F(" / 1023, napeti priblizne "));
    Serial.print(hodnota * (5.0 / 1023.0), 2);
    Serial.print(F(" V, cil rucicky: "));
    Serial.print(cilMotoru * 1.8, 1);
    Serial.println(F(" stupnu (0=12h, 90=3h, 180=6h)"));
  }
  // millis() vraci milisekundy od startu. Rozdil funguje i pri preteceni casu.
  unsigned long ted = millis();
  if (ted - posledniPrevodMs >= INTERVAL_ADC_MS && !(ADCSRA & _BV(ADSC))) {
    posledniPrevodMs = ted;
    ADCSRA |= _BV(ADSC);
  }
}

// Vlastni funkce programu: vypise podporovane prikazy.
void napoveda() {
  // println(data) vypise data jako text a prida konec radku CRLF.
  // F("text") je makro: na Unu ponecha konstantni text ve flash a setri RAM.
  // Viz take dokumentace Serial.print(), cast o F():
  // https://docs.arduino.cc/language-reference/en/functions/communication/serial/print/
  Serial.println(F("Prikazy: pomoc, zapni, vypni, stav, echo TEXT"));
}

// Vlastni funkce programu: potvrdi prijem a provede prikaz z celeho radku.
void zpracujRadek(String prikaz) {
  // Automaticke echo potvrdi prijem i u prazdneho nebo neznameho prikazu.
  // print(data) vypise text bez pridani konce radku; cisla formatuje jako text.
  // print(), println() i write() vraceji pocet zapsanych bajtu (zde jej nepouzivame).
  Serial.print(F("Prijato: ["));
  Serial.print(prikaz);
  Serial.println(F("]"));
  // trim() upravi primo tento String: odstrani krajni bile znaky, nejen mezery.
  prikaz.trim();
  // length() vraci delku obsahu bez ukoncovaci nuly; na Unu jde o pocet bajtu.
  // Znak s diakritikou v UTF-8 muze zabirat vice bajtu.
  if (prikaz.length() == 0) return;

  if (prikaz == "pomoc") {
    napoveda();
  } else if (prikaz == "zapni" || prikaz == "vypni") {
    ledSviti = (prikaz == "zapni");
    // digitalWrite(pin, hodnota) nastavi vystup na HIGH nebo LOW.
    digitalWrite(LED_PIN, ledSviti ? HIGH : LOW);
    Serial.println(ledSviti ? F("LED zapnuta.") : F("LED vypnuta."));
  } else if (prikaz == "stav") {
    Serial.println(ledSviti ? F("LED sviti.") : F("LED nesviti."));
  } else if (prikaz.startsWith("echo ")) {  // startsWith(prefix) overi zacatek textu.
    Serial.print(F("Prijaty text: "));
    // substring(od) vrati novy String od indexu 5 do konce; indexy jsou od nuly.
    Serial.println(prikaz.substring(5));
  } else {
    Serial.print(F("Neznamy prikaz: "));
    Serial.println(prikaz);
    napoveda();
  }
}

// setup() zavola Arduino jednou po zapnuti nebo resetu; pripravuje hardware.
void setup() {
  pripravMotor();
  pinMode(LED_PIN, OUTPUT);  // pinMode(pin, rezim) nastavi pin jako vystup.
  digitalWrite(LED_PIN, LOW);  // LOW na vystupnim pinu zde zhasne vestavenou LED.
  Serial.begin(9600);  // begin(rychlost) spusti seriovou linku na 9600 bit/s, vychozi 8N1.
  // reserve(kapacita) predem vyhradi pamet pro String, obsah ani delku nemeni.
  // Neni to limit delky: ten hlidame sami v loop().
  radek.reserve(MAX_DELKA);
  Serial.println(F("Cteni seriove linky je pripraveno (9600 baud)."));
  napoveda();
  pripravADC();  // Globalni preruseni uz zapnulo jadro Arduino pred setup().
}

// loop() Arduino po setup() vola stale dokola, dokud deska bezi.
void loop() {
  obsluzMotor();
  obsluzADC();
  // available() vraci pocet bajtu cekajicich ve vstupnim seriovem bufferu.
  // Bez cekani na cely radek muze Arduino mezitim delat i jinou praci.
  while (Serial.available() > 0) {
    // read() odebere jeden bajt a vrati jej jako int; bez dat vraci -1.
    // Zde uz available() potvrdilo data, takze hodnotu ulozime do char.
    char znak = Serial.read();
    // Enter muze poslat CR, LF nebo CRLF. CRLF zpracujeme jen jednou.
    if (znak == '\n' && predchoziBylCR) {
      predchoziBylCR = false;
      continue;
    }
    predchoziBylCR = (znak == '\r');

    if (znak == '\n' || znak == '\r') {
      Serial.println();  // Varianta bez argumentu posle pouze konec radku CRLF.
      if (prilisDlouhy) {
        Serial.println(F("Chyba: radek ma vice nez 64 znaku. Posli kratsi."));
      } else {
        zpracujRadek(radek);
      }
      radek = "";
      prilisDlouhy = false;
    } else if (!prilisDlouhy) {
      // Echo kazdeho znaku funguje jeste pred Enterem.
      // write(bajt) odesle puvodni bajt bez prevodu na cislice a bez konce radku.
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
