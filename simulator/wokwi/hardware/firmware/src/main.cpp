/*
 * Zde začíná program ECU, který běží na desce ESP32 nebo Arduino Mega.
 * Rozhodování je v ecu_controller.h. Tento soubor ho propojuje se skutečnými
 * příkazy desky: čtením pinů, měřením času a zapínáním výstupů.
 *
 * Představ si tři spolupracující pomocníky:
 *   CKP a CMP: „Přišla značka polohy motoru!“ -> crank() a cam().
 *   Časovač:  „Je čas zkontrolovat výstupy!“ -> tick(), běžně každých 25 us.
 *   loop():   „Jednou za chvíli vypíšu, co se děje.“
 *
 * Postup čtení pro začátečníka:
 *   1. Prohlédni si setup(): připraví desku jednou po zapnutí.
 *   2. Prohlédni si loop(): opakuje se stále dokola.
 *   3. Pak se vrať k funkcím ckp_edge(), cmp_edge() a output_tick().
 *      Ty nevolá loop(), ale události snímačů a časovače.
 *
 * Firmware přijímá polohu přes piny, nikoli jako simulační JSON zprávy.
 * Kanál TPS používáme jako výukový pedál. ECU z něj zatím přímo vypočítá dávku.
 */
#include "ecu_controller.h"
#include <Arduino.h> // pinMode, digitalWrite, micros a další příkazy Arduino.

// Řádky začínající # zpracuje překladač ještě před překladem samotného programu.
// #if vybere variantu pro naši desku. ESP32 a Mega mají jiné časovače a jiné CPU.
#if defined(ARDUINO_ARCH_AVR)
#include <avr/interrupt.h>
#endif

// Vytvoříme jeden řadič. Pamatuje si otáčky, polohu i zapnuté výstupy.
// static zde nechává proměnnou patřit tomuto souboru; žije po celou dobu programu.
static EcuController ecu;
// Pět naměřených hodnot: MAP (tlak), TPS (plyn), IAT (teplota vzduchu),
// CLT (teplota chladicí kapaliny) a lambda (údaj o směsi paliva a vzduchu).
// Zatím ukládáme čísla z převodníku ADC, nikoli fyzikální jednotky kPa či °C.
static unsigned adc[5];

#if defined(ARDUINO_ARCH_ESP32)
// * označuje ukazatel: output_timer odkazuje na časovač připravený knihovnou.
static hw_timer_t *output_timer;
// Přerušení a běžný program mohou na ESP32 přistupovat ke stejnému řadiči.
// Zámek je jako cedulka „obsazeno“: nedovolí jim současně měnit společné údaje.
static portMUX_TYPE ecu_lock = portMUX_INITIALIZER_UNLOCKED;
// ISR je funkce obsluhující přerušení. IRAM_ATTR označuje její umístění v paměti ESP32.
// #define nám dovolí používat společné názvy i pro druhý typ desky.
#define ECU_ISR IRAM_ATTR
#define LOCK_ISR() portENTER_CRITICAL_ISR(&ecu_lock)
#define UNLOCK_ISR() portEXIT_CRITICAL_ISR(&ecu_lock)
#else
// AVR při běžné obsluze přerušení další přerušení automaticky nepouští.
// Zde tedy tyto pomocné značky nepotřebujeme; překladač je nahradí prázdným textem.
#define ECU_ISR
#define LOCK_ISR()
#define UNLOCK_ISR()
#endif

// Tuto pomocnou funkci předáváme řadiči jako write.
// ignition = true vybere zapalování, false vstřikovač.
// channel je číslo kanálu od 0, value je požadovaná elektrická úroveň pinu.
static void ECU_ISR write_output(bool ignition, unsigned channel, unsigned value) {
  // Zápis podmínka ? A : B vybere A při splnění podmínky, jinak B.
  digitalWrite(ignition ? IGNITION_PINS[channel] : INJECTOR_PINS[channel], value);
}

// Přerušení si představ jako zvonek u dveří: procesor na chvíli odloží běžnou práci
// a rychle obslouží novou událost. Díky tomu nemusíme pořád kontrolovat snímač v loop().
// Uvnitř přerušení nečekáme pomocí delay() a nevypisujeme dlouhé texty na Serial.
static void ECU_ISR ckp_edge() {
  LOCK_ISR();
  // micros() vrátí čas od spuštění desky v mikrosekundách. Řadič potřebuje čas zubu.
  ecu.crank(micros());
  UNLOCK_ISR();
}
static void ECU_ISR cmp_edge() {
  LOCK_ISR();
  ecu.cam(micros());
  UNLOCK_ISR();
}
static void ECU_ISR output_tick() {
  LOCK_ISR();
  // Časovač pravidelně kontroluje začátky i konce pulzů.
  // Například 3000us vstřik se při 25us kroku kontroluje přibližně 120krát.
  // Kontrola po krocích není totéž jako nekonečně přesné spojité měření času.
  ecu.tick(micros(), write_output);
  UNLOCK_ISR();
}
#if defined(ARDUINO_ARCH_AVR)
// Jméno TIMER1_COMPA_vect říká AVR, že toto je obsluha porovnání časovače Timer1.
ISR(TIMER1_COMPA_vect) {
  output_tick();
}
#endif

// Arduino zavolá setup() právě jednou po zapnutí nebo resetu.
void setup() {
  Serial.begin(ECU_DIAG_BAUD);
  Serial.println("ECU_RESET gpio-only demo");
  for (unsigned i = 0; i < ECU_CYLINDERS; i++) {
    // Nejdříve nastavíme všechny řízené piny jako výstupy a necháme je vypnuté.
    // ! obrací logickou hodnotu: potřebujeme opak aktivní úrovně z konfigurace.
    pinMode(INJECTOR_PINS[i], OUTPUT);
    digitalWrite(INJECTOR_PINS[i], !ECU_INJ_ACTIVE);
    pinMode(IGNITION_PINS[i], OUTPUT);
    digitalWrite(IGNITION_PINS[i], !ECU_IGN_ACTIVE);
  }
  pinMode(ECU_CKP_PIN, INPUT);
  pinMode(ECU_CMP_PIN, INPUT);
  // Připojíme „zvonky“ snímačů k jejich obslužným funkcím.
  // RISING znamená přechod 0 -> 1, FALLING přechod 1 -> 0.
  // Zvolená hrana závisí na polaritě snímače v konfiguraci.
  attachInterrupt(digitalPinToInterrupt(ECU_CKP_PIN), ckp_edge, ECU_CKP_ACTIVE ? RISING : FALLING);
  attachInterrupt(digitalPinToInterrupt(ECU_CMP_PIN), cmp_edge, ECU_CMP_ACTIVE ? RISING : FALLING);
#if defined(ARDUINO_ARCH_ESP32)
  // ADC převádí napětí na číslo. 12 bitů dává 4096 možných hodnot: 0 až 4095.
  analogReadResolution(12);
  // ESP32 s použitou knihovnou Arduino 2.x: časovač č. 0, dělička 80, počítání nahoru.
  // Z 80 MHz tím vznikne krok 1 MHz, tedy jeden krok za mikrosekundu.
  output_timer = timerBegin(0, 80, true);
  timerAttachInterrupt(output_timer, &output_tick, true);
  // Alarm po ECU_TIMER_US krocích; true znamená opakovat automaticky.
  // Výchozích 25 us znamená 1 000 000 / 25 = 40 000 kontrol za sekundu.
  timerAlarmWrite(output_timer, ECU_TIMER_US, true);
  timerAlarmEnable(output_timer);
#elif defined(ARDUINO_ARCH_AVR)
  // Následující část nastavuje přímo řídicí registry časovače Arduino Mega.
  // Registr si představ jako řadu malých přepínačů uvnitř procesoru.
  // Pro první čtení stačí pochopit cíl: stejný pravidelný krok jako u ESP32.
  noInterrupts(); // Během změny nastavení nám obsluha přerušení nesmí vstoupit do práce.
  TCCR1A = 0;
  // WGM12 zapíná režim CTC: počítadlo po dosažení cíle začíná znovu od nuly.
  // CS11 volí dělení hodin osmi. | spojuje dvě sady přepínačů, _BV vytváří jeden bit.
  TCCR1B = _BV(WGM12) | _BV(CS11);
  // Mega má 16 MHz. Po dělení 8 má časovač 2 MHz, tedy krok 0,5 us.
  // Pro 25 us potřebuje 50 kroků. Cíl je 49, protože počítá i nulu: 0..49.
  OCR1A = (F_CPU / 8 / 1000000) * ECU_TIMER_US - 1;
  TIMSK1 |= _BV(OCIE1A); // Povolí přerušení při dosažení nastaveného cíle.
  interrupts();
#endif
}

// loop() se po dokončení setup() opakuje stále dokola.
// O přesné řízení se starají snímače a časovač výše. Tady připravujeme čitelný výpis.
void loop() {
  // Vstupy čteme každých 10 ms, i když dlouhý diagnostický výpis přijde jen po 100 ms.
  static uint32_t last_inputs, last_report;
  if (millis() - last_inputs >= 10) {
    last_inputs = millis();
    for (unsigned i = 0; i < 5; i++)
      adc[i] = analogRead(ANALOG_PINS[i]);
#if defined(ARDUINO_ARCH_ESP32)
    portENTER_CRITICAL(&ecu_lock);
    ecu.set_accelerator_adc(adc[1], 4095);
    portEXIT_CRITICAL(&ecu_lock);
#else
    noInterrupts();
    ecu.set_accelerator_adc(adc[1], 1023);
    interrupts();
#endif
  }
  if (millis() - last_report < 100)
    return;
  last_report = millis();

  // Krátce si uděláme společnou „fotku“ údajů řadiče. Během kopírování se údaje
  // nesmí měnit: jinak bychom mohli přečíst polovinu starého a polovinu nového čísla.
  // To je zvlášť důležité na osmibitovém AVR, které čte 32bitové číslo po částech.
#if defined(ARDUINO_ARCH_ESP32)
  portENTER_CRITICAL(&ecu_lock);
#else
  noInterrupts();
#endif
  double rpm = ecu.rpm, cycle = ecu.phase_at_edge;
  double pedal = ecu.accelerator, requested_rpm = ecu.requested_rpm;
  uint32_t fuel_us = ecu.injection_us;
  bool synced = ecu.synced;
  unsigned slot = ecu.slot;
  uint32_t edges = ecu.edges, cam = ecu.cam_edges, errors = ecu.errors;
#if defined(ARDUINO_ARCH_ESP32)
  portEXIT_CRITICAL(&ecu_lock);
#else
  interrupts();
#endif

  // Teď už vypisujeme kopie a neblokujeme kvůli dlouhému textu obsluhu motoru.
  // Samostatný UART TX -> DIAG_RX chipu -> Chips Console přenáší pouze diagnostiku.
  // Není to hostitelský UART pro simulační zprávy.
  // Příklad významu položek:
  //   RPM=1000.0  -> přibližně tisíc otáček za minutu;
  //   SYNC=1      -> CKP a CMP potvrdily polohu cyklu, 0 znamená nepotvrzenou polohu;
  //   CYCLE=...   -> úhel při posledním přijatém zubu, nikoli přesný úhel v čase výpisu;
  //   TOOTH=...   -> číslo polohy zubu po mezeře (po nalezení mezery);
  //   CKP/CMP     -> počty impulzů; ERR -> počet zjištěných nesrovnalostí;
  //   ADC=...     -> pět syrových hodnot převodníku, pro ESP32 0..4095, Mega 0..1023.
  Serial.print("RPM=");
  Serial.print(rpm, 1); // Druhý argument 1 požaduje jedno desetinné místo.
  Serial.print(" SYNC=");
  Serial.print(synced);
  Serial.print(" CYCLE=");
  Serial.print(cycle, 1);
  Serial.print(" TOOTH=");
  Serial.print(slot);
  Serial.print(" CKP=");
  Serial.print(edges);
  Serial.print(" CMP=");
  Serial.print(cam);
  Serial.print(" ERR=");
  Serial.print(errors);
  Serial.print(" PEDAL=");
  Serial.print(pedal, 3);
  Serial.print(" RPM_GOAL=");
  if (requested_rpm < 0)
    Serial.print("off");
  else
    Serial.print(requested_rpm, 0);
  Serial.print(" FUEL_US=");
  Serial.print(fuel_us);
  Serial.print(" ADC=");
  for (unsigned i = 0; i < 5; i++) {
    Serial.print(adc[i]);
    Serial.print(i == 4 ? '\n' : ','); // Mezi hodnotami čárka, po poslední nový řádek.
  }
}
