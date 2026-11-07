/* Vyukovy kontroler kvadrokoptery v X konfiguraci pro Wokwi.
 * Arduino Uno + MPU6050 + joystick + plyn + ARM + ctyri ukazatele vykonu.
 * Nejde o firmware overeny pro skutecny let. Wokwi nesimuluje dynamiku dronu.
 * Servo ukazatele zastupuji vystupy pro ESC, nejsou to vrtulove motory.
 */
#include <Arduino.h>
#include <Wire.h>
#include <avr/interrupt.h>
#include <util/atomic.h>
#include "controller.h"

const byte IMU = 0x68;
const byte ARM_PIN = 2;
const byte BUZZER_PIN = 4;
const byte MOTOR_PINS[4] = {5, 6, 9, 10};
const unsigned long PERIODA_US = 10000;  // Cilova frekvence rizeni 100 Hz.
volatile uint16_t pulzy[4] = {1000, 1000, 1000, 1000};
uint16_t vystupy[4] = {1000, 1000, 1000, 1000};
bool aktivni = false, imuOK = false, povolenaHrana = false;
bool filtrInicializovan = false;
float roll = 0, pitch = 0, bias[3] = {0, 0, 0};
unsigned long posledniRizeni = 0, posledniVypis = 0;
int plyn = 0;

// Timer1 generuje ctyri servo/ESC pulzy v ramci 20 ms, nezavisle na vypisech.
// CTC, delicka 8: 16 MHz / 8 = 2 MHz, jeden tik = 0.5 us.
// Timer1 je vyhrazen temto vystupum; nepridavej knihovnu Servo ani analogWrite D9/D10.
ISR(TIMER1_COMPA_vect) {
  static byte kanal = 0;
  static uint16_t sirky[4];
  static uint16_t soucet = 0;
  if (kanal > 0) digitalWrite(MOTOR_PINS[kanal - 1], LOW);
  if (kanal == 0) {
    soucet = 0;
    for (byte i = 0; i < 4; i++) sirky[i] = pulzy[i];
  }
  if (kanal < 4) {
    digitalWrite(MOTOR_PINS[kanal], HIGH);
    soucet += sirky[kanal];
    OCR1A = sirky[kanal] * 2 - 1;
    kanal++;
  } else {
    OCR1A = (20000 - soucet) * 2 - 1;
    kanal = 0;
  }
}

void publikujVystupy() {
  // AVR je 8bitovy: cele ctyri hodnoty predame ISR najednou.
  ATOMIC_BLOCK(ATOMIC_RESTORESTATE) {
    for (byte i = 0; i < 4; i++) pulzy[i] = vystupy[i];
  }
}

void zastav() {
  aktivni = false;
  for (byte i = 0; i < 4; i++) vystupy[i] = 1000;
  publikujVystupy();
  digitalWrite(LED_BUILTIN, LOW);
}

bool zapisRegistr(byte registr, byte hodnota) {
  Wire.beginTransmission(IMU);
  Wire.write(registr);
  Wire.write(hodnota);
  return Wire.endTransmission() == 0;
}

bool ctiIMU(float a[3], float g[3]) {
  // Souvisle cteme 14 bajtu od ACCEL_XOUT_H, pres teplotu az po gyroskop.
  Wire.beginTransmission(IMU);
  Wire.write(0x3B);
  if (Wire.endTransmission(false) != 0) return false;
  if (Wire.requestFrom(IMU, static_cast<byte>(14)) != 14) return false;
  int16_t data[7];
  for (byte i = 0; i < 7; i++) {
    uint16_t hi = Wire.read();
    data[i] = static_cast<int16_t>((hi << 8) | Wire.read());
  }
  for (byte i = 0; i < 3; i++) {
    a[i] = data[i] / 16384.0f;  // Rozsah +/-2 g.
    g[i] = data[i + 4] / 131.0f;  // Rozsah +/-250 stupnu/s.
  }
  return true;
}

bool pripravIMU() {
  // Registry podle oficialni mapy MPU6050, odkazy jsou v README.
  if (!zapisRegistr(0x6B, 0x01) || !zapisRegistr(0x1B, 0)
      || !zapisRegistr(0x1C, 0) || !zapisRegistr(0x1A, 3)
      || !zapisRegistr(0x19, 9)) return false;
  delay(100);
  Serial.println(F("Kalibrace gyroskopu: nech MPU6050 v klidu a vodorovne."));
  for (byte n = 0; n < 100; n++) {
    float a[3], g[3];
    if (!ctiIMU(a, g)) return false;
    for (byte i = 0; i < 3; i++) bias[i] += g[i] / 100.0f;
    delay(10);
  }
  return true;
}

void setup() {
  Serial.begin(115200);
  pinMode(ARM_PIN, INPUT_PULLUP);  // Sepnuti na GND znamena pozadavek ARM.
  pinMode(LED_BUILTIN, OUTPUT);
  pinMode(BUZZER_PIN, OUTPUT);
  for (byte pin : MOTOR_PINS) { pinMode(pin, OUTPUT); digitalWrite(pin, LOW); }
  ATOMIC_BLOCK(ATOMIC_RESTORESTATE) {
    TCCR1A = 0;
    TCCR1B = 0;
    TCNT1 = 0;
    OCR1A = 199;
    TIFR1 = _BV(OCF1A);
    TIMSK1 = _BV(OCIE1A);
    TCCR1B = _BV(WGM12) | _BV(CS11);
  }
  Wire.begin();
  Wire.setClock(400000);
  Wire.setWireTimeout(3000, true);  // Chyba I2C nesmi zustat nekonecne cekat.
  imuOK = pripravIMU();
  Serial.println(imuOK ? F("IMU OK. Plyn na nulu, prepinac DISARM -> ARM.")
                       : F("CHYBA IMU: vystupy STOP. Oprav zapojeni a restartuj."));
  if (!imuOK) tone(BUZZER_PIN, 500, 400);
  posledniRizeni = micros();
}

void loop() {
  // Vypnuti ARM zpracujeme i mezi dvema vypocty regulace.
  bool pozadavekArm = digitalRead(ARM_PIN) == LOW;
  if (!pozadavekArm) {
    povolenaHrana = true;
    if (aktivni) zastav();
  }
  unsigned long ted = micros();
  if (ted - posledniRizeni < PERIODA_US) return;
  float dt = (ted - posledniRizeni) / 1000000.0f;
  posledniRizeni = ted;
  plyn = analogRead(A2);
  float cilRoll = pozadavekOsy(analogRead(A0), true);  // Vpravo = kladny roll.
  float cilPitch = pozadavekOsy(analogRead(A1));  // Nahoru = predek nahoru.
  float a[3], g[3];
  bool platne = imuOK && ctiIMU(a, g);
  if (!platne || dt > 0.05f) {
    zastav();
    povolenaHrana = false;  // Po chybe vyzadujeme nove vypnuti/zapnuti ARM.
    filtrInicializovan = false;
    if (millis() - posledniVypis >= 500) {
      posledniVypis = millis();
      Serial.println(F("FAILSAFE: chyba IMU nebo dlouha perioda. DISARM a zkontroluj IMU."));
    }
    return;
  }
  for (byte i = 0; i < 3; i++) g[i] -= bias[i];
  float rollAcc = atan2f(a[1], a[2]) * RAD_TO_DEG;
  float pitchAcc = atan2f(-a[0], sqrtf(a[1] * a[1] + a[2] * a[2])) * RAD_TO_DEG;
  if (!filtrInicializovan) {
    roll = rollAcc; pitch = pitchAcc; filtrInicializovan = true;
  } else {
    float alfa = 0.5f / (0.5f + dt);  // Komplementarni filtr, casova konstanta 0.5 s.
    roll = alfa * (roll + g[0] * dt) + (1 - alfa) * rollAcc;
    pitch = alfa * (pitch + g[1] * dt) + (1 - alfa) * pitchAcc;
  }
  if (pozadavekArm && povolenaHrana) {
    povolenaHrana = false;  // I neuspesny pokus vyzaduje novou hranu prepinace.
    if (lzeAktivovat(plyn, roll, pitch, cilRoll, cilPitch)) {
      aktivni = true;
      digitalWrite(LED_BUILTIN, HIGH);
      tone(BUZZER_PIN, 1800, 100);
      Serial.println(F("ARM: vystupy aktivni."));
    } else {
      tone(BUZZER_PIN, 400, 150);
      Serial.println(F("ARM odmitnut: plyn na nulu, joystick doprostred, srovnej IMU."));
    }
  }
  if (aktivni && (fabsf(roll) > 60 || fabsf(pitch) > 60)) {
    zastav(); povolenaHrana = false;
    Serial.println(F("FAILSAFE: naklon nad 60 stupnu."));
  }
  if (aktivni) {
    // Vyukovy PD regulator uhlu s tlumenim uhlove rychlosti. Bez integratoru.
    float r = omez(5 * (cilRoll - roll) - 0.8f * g[0], -120, 120);
    float p = omez(5 * (cilPitch - pitch) - 0.8f * g[1], -120, 120);
    float y = omez(-1.5f * g[2], -80, 80);  // Pouze tlumeni yaw, bez drzeni kurzu.
    smichejMotory(plyn, r, p, y, vystupy);
    publikujVystupy();
  }
  if (millis() - posledniVypis >= 250) {
    posledniVypis = millis();
    Serial.print(aktivni ? F("ARM ") : F("DISARM "));
    Serial.print(F("plyn=")); Serial.print(plyn);
    Serial.print(F(" roll=")); Serial.print(roll, 1);
    Serial.print(F(" pitch=")); Serial.print(pitch, 1);
    Serial.print(F(" M1..M4 [us]:"));
    for (uint16_t hodnota : vystupy) { Serial.print(' '); Serial.print(hodnota); }
    Serial.println();
  }
}
