// Demonstrační ECU pro Mega: UART0 host, UART1 lokální Custom Chip.
// Piny časuje Wokwi; příchozí JSON nikdy přímo nespouští CKP/CMP hranu.
#include "legacy_time.h"
#include <Arduino.h>
#include <math.h>
#include <stdlib.h>
#include <string.h>
#include <util/atomic.h>

static char input[2048];
static size_t used;
static bool discard;
static uint32_t sequence, lastState, nextPulse;
static float rpm = 900, injectionMs = 3;
static uint8_t activeChannel;
static bool injecting, charging, online;
static LegacyTime clock_map;
static LegacyPulse pulses[2][4];
static uint32_t injectionEnd, sparkAt;
static char chipLine[96];
static size_t chipUsed;
static volatile uint32_t ckpCount, cmpCount;

void ckpRise() {
  ++ckpCount;
}
void cmpRise() {
  ++cmpCount;
}

// Úzký čteč čísel známých klíčů hostitelského schématu, bez dynamické alokace.
bool number(const char *json, const char *key, double &value) {
  char pattern[64];
  snprintf(pattern, sizeof(pattern), "\"%s\"", key);
  const char *p = strstr(json, pattern);
  if (!p || !(p = strchr(p, ':')))
    return false;
  char *end;
  value = strtod(p + 1, &end);
  return end != p + 1 && isfinite(value);
}

void envelope(const char *type, uint32_t time) {
  Serial.print(F("{\"version\":1,\"type\":\""));
  Serial.print(type);
  Serial.print(F("\",\"source\":\"demo-ecu\",\"sequence\":"));
  Serial.print(++sequence);
  Serial.print(F(",\"simulation_time_us\":"));
  Serial.print(time);
  Serial.print(F(",\"error\":null,\"data\":"));
}
void event(const char *signal, const char *action, uint8_t channel, uint32_t timestamp,
           uint32_t duration = 0) {
  envelope("ecu_event", timestamp);
  Serial.print(F("{\"signal\":\""));
  Serial.print(signal);
  Serial.print(F("\",\"action\":\""));
  Serial.print(action);
  Serial.print(F("\",\"channel\":"));
  Serial.print(channel);
  Serial.print(F(",\"simulation_time_us\":"));
  Serial.print(timestamp);
  Serial.print(F(",\"duration_us\":"));
  Serial.print(duration);
  Serial.println(F("}}"));
}
void stateFrame() {
  if (!strstr(input, "\"engine_state\""))
    return;
  uint32_t time, seq, epoch = 0;
  double r, map, tps, iat, clt, lambda, version, speed = 1;
  if (!number(input, "version", version) || version != 1 ||
      !read_u32(input, "simulation_time_us", time) || !read_u32(input, "sequence", seq) ||
      !number(input, "rpm", r) || !number(input, "map_kpa", map) || !number(input, "tps", tps) ||
      !number(input, "iat_c", iat) || !number(input, "clt_c", clt) ||
      !number(input, "lambda_value", lambda))
    return;
  read_u32(input, "bridge_epoch", epoch);
  number(input, "simulation_speed", speed);
  if (speed <= 0 || speed > 1)
    return;
  if (clock_map.update(time, micros(), epoch, speed)) {
    for (unsigned kind = 0; kind < 2; kind++)
      for (unsigned ch = 0; ch < 4; ch++)
        pulses[kind][ch].active = false;
    for (int pin = 22; pin < 30; pin++)
      digitalWrite(pin, LOW);
    injecting = charging = false;
  }
  rpm = constrain(r, 0, 7500);
  injectionMs = constrain(2.7 + .002 * (1200 - rpm), .5, 6);
  lastState = millis();
  online = true;
  // Kompaktní lokální UART: hodnoty krát 100, aby WASM nepotřeboval float scanf.
  Serial1.print(F("S "));
  Serial1.print((long)(rpm * 100));
  Serial1.print(' ');
  Serial1.print((long)(map * 100));
  Serial1.print(' ');
  Serial1.print((long)(tps * 100));
  Serial1.print(' ');
  Serial1.print((long)(iat * 100));
  Serial1.print(' ');
  Serial1.print((long)(clt * 100));
  Serial1.print(' ');
  Serial1.println((long)(lambda * 100));
  envelope("clock_sync", (uint32_t)time);
  Serial.print(F("{\"echo_sequence\":"));
  Serial.print((uint32_t)seq);
  Serial.print(F(",\"ecu_time_us\":"));
  Serial.print(micros());
  uint32_t crank_count, cam_count;
  // AVR čte 32bitové čítače po bajtech: přerušení nesmí změnit jejich polovinu.
  ATOMIC_BLOCK(ATOMIC_RESTORESTATE) {
    crank_count = ckpCount;
    cam_count = cmpCount;
  }
  Serial.print(F(",\"ckp_edges\":"));
  Serial.print(crank_count);
  Serial.print(F(",\"cmp_edges\":"));
  Serial.print(cam_count);
  Serial.println(F("}}"));
}
void setup() {
  Serial.begin(1000000);
  Serial1.begin(1000000);
  pinMode(LED_BUILTIN, OUTPUT);
  for (int pin = 22; pin < 30; ++pin) {
    pinMode(pin, OUTPUT);
    digitalWrite(pin, LOW);
  }
  pinMode(2, INPUT);
  pinMode(3, INPUT);
  attachInterrupt(digitalPinToInterrupt(2), ckpRise, RISING);
  attachInterrupt(digitalPinToInterrupt(3), cmpRise, RISING);
}
void loop() {
  // Limit na iteraci zajišťuje, že dlouhý vstup nevyhladoví časování výstupů.
  for (uint8_t i = 0; i < 32 && Serial.available(); ++i) {
    char c = Serial.read();
    if (c == '\n') {
      if (!discard) {
        input[used] = 0;
        stateFrame();
      }
      used = 0;
      discard = false;
    } else if (!discard) {
      if (used < sizeof(input) - 1)
        input[used++] = c;
      else {
        discard = true;
        used = 0;
      }
    }
  }
  // Chip zachytí fyzické hrany na pinech. Konzole chipu obsahuje jejich čas Wokwi.
  while (Serial1.available()) {
    char c = Serial1.read();
    if (c == '\n') {
      chipLine[chipUsed] = 0;
      chipUsed = 0;
      unsigned long time, kind, channel, level;
      if (sscanf(chipLine, "E %lu %lu %lu %lu", &time, &kind, &channel, &level) == 4 &&
          channel < 4 && kind < 2 && level < 2) {
        if (!online)
          continue;
        uint32_t mapped = clock_map.map(time, micros()), duration = 0;
        if (level)
          pulses[kind][channel].start(time, mapped, clock_map.ratio);
        else if (!pulses[kind][channel].end(time, mapped, duration))
          continue;
        event(kind ? "ignition" : "injector",
              kind ? (level ? "charge" : "spark") : (level ? "start" : "end"), channel, mapped,
              duration);
      }
    } else if (chipUsed < sizeof(chipLine) - 1)
      chipLine[chipUsed++] = c;
  }
  uint32_t now = micros();
  if (injecting && (int32_t)(now - injectionEnd) >= 0) {
    digitalWrite(22 + activeChannel, LOW);
    injecting = false;
  }
  if (charging && (int32_t)(now - sparkAt) >= 0) {
    digitalWrite(26 + activeChannel, LOW);
    charging = false;
  }
  if (online && millis() - lastState > 1000) {
    online = false;
    Serial1.println(F("S 0 2500 0 2500 8500 100"));
  }
  if (online && rpm > 0 && !injecting && !charging && (int32_t)(now - nextPulse) >= 0) {
    activeChannel = (activeChannel + 1) % 4;
    injectionEnd = now + (uint32_t)(injectionMs * 1000);
    sparkAt = now + 2000;
    nextPulse = now + (uint32_t)(120000000.0 / (rpm * 4));
    injecting = charging = true;
    digitalWrite(22 + activeChannel, HIGH);
    digitalWrite(26 + activeChannel, HIGH);

    digitalWrite(LED_BUILTIN, !digitalRead(LED_BUILTIN));
  }
}
