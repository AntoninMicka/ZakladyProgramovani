// Produkční hranice: tento firmware zná pouze GPIO/ADC a vlastní diagnostiku.
#include "ecu_controller.h"
#include <Arduino.h>
#if defined(ARDUINO_ARCH_AVR)
#include <avr/interrupt.h>
#endif
static EcuController ecu;
static unsigned adc[5];
#if defined(ARDUINO_ARCH_ESP32)
static hw_timer_t *output_timer;
static portMUX_TYPE ecu_lock = portMUX_INITIALIZER_UNLOCKED;
#define ECU_ISR IRAM_ATTR
#define LOCK_ISR() portENTER_CRITICAL_ISR(&ecu_lock)
#define UNLOCK_ISR() portEXIT_CRITICAL_ISR(&ecu_lock)
#else
#define ECU_ISR
#define LOCK_ISR()
#define UNLOCK_ISR()
#endif
static void ECU_ISR write_output(bool ignition, unsigned channel, unsigned value) {
  digitalWrite(ignition ? IGNITION_PINS[channel] : INJECTOR_PINS[channel], value);
}
static void ECU_ISR ckp_edge() {
  LOCK_ISR();
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
  ecu.tick(micros(), write_output);
  UNLOCK_ISR();
}
#if defined(ARDUINO_ARCH_AVR)
ISR(TIMER1_COMPA_vect) {
  output_tick();
}
#endif
void setup() {
  Serial.begin(ECU_DIAG_BAUD);
  Serial.println("ECU_RESET gpio-only demo");
  for (unsigned i = 0; i < ECU_CYLINDERS; i++) {
    pinMode(INJECTOR_PINS[i], OUTPUT);
    digitalWrite(INJECTOR_PINS[i], !ECU_INJ_ACTIVE);
    pinMode(IGNITION_PINS[i], OUTPUT);
    digitalWrite(IGNITION_PINS[i], !ECU_IGN_ACTIVE);
  }
  pinMode(ECU_CKP_PIN, INPUT);
  pinMode(ECU_CMP_PIN, INPUT);
  attachInterrupt(digitalPinToInterrupt(ECU_CKP_PIN), ckp_edge, ECU_CKP_ACTIVE ? RISING : FALLING);
  attachInterrupt(digitalPinToInterrupt(ECU_CMP_PIN), cmp_edge, ECU_CMP_ACTIVE ? RISING : FALLING);
#if defined(ARDUINO_ARCH_ESP32)
  analogReadResolution(12);
  output_timer = timerBegin(0, 80, true);
  timerAttachInterrupt(output_timer, &output_tick, true);
  timerAlarmWrite(output_timer, ECU_TIMER_US, true);
  timerAlarmEnable(output_timer);
#elif defined(ARDUINO_ARCH_AVR)
  noInterrupts();
  TCCR1A = 0;
  TCCR1B = _BV(WGM12) | _BV(CS11);
  OCR1A = (F_CPU / 8 / 1000000) * ECU_TIMER_US - 1;
  TIMSK1 |= _BV(OCIE1A);
  interrupts();
#endif
}
void loop() {
  static uint32_t last_report;
  if (millis() - last_report < 100)
    return;
  last_report = millis();
  for (unsigned i = 0; i < 5; i++)
    adc[i] = analogRead(ANALOG_PINS[i]);
#if defined(ARDUINO_ARCH_ESP32)
  portENTER_CRITICAL(&ecu_lock);
#else
  noInterrupts();
#endif
  double rpm = ecu.rpm, cycle = ecu.phase_at_edge;
  bool synced = ecu.synced;
  unsigned slot = ecu.slot;
  uint32_t edges = ecu.edges, cam = ecu.cam_edges, errors = ecu.errors;
#if defined(ARDUINO_ARCH_ESP32)
  portEXIT_CRITICAL(&ecu_lock);
#else
  interrupts();
#endif
  // Oddělený UART TX → DIAG_RX chipu → Chips Console. Nejde do simulačního UART.
  Serial.print("RPM=");
  Serial.print(rpm, 1);
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
  Serial.print(" ADC=");
  for (unsigned i = 0; i < 5; i++) {
    Serial.print(adc[i]);
    Serial.print(i == 4 ? '\n' : ',');
  }
}
