#pragma once
#include <math.h>
#include <stdint.h>

// Ciste vypocty bez zavislosti na Arduinu: lze overovat i na pocitaci.
inline float omez(float hodnota, float minimum, float maximum) {
  return hodnota < minimum ? minimum : (hodnota > maximum ? maximum : hodnota);
}

// Joystick: stredova mrtva zona, mimo ni plynuly pozadavek +/-20 stupnu.
inline float pozadavekOsy(int adc, bool obratit = false) {
  float osa = omez((adc - 512) / 511.0f, -1.0f, 1.0f);
  float velikost = fabsf(osa);
  float vysledek = velikost <= 0.06f ? 0.0f : (velikost - 0.06f) / 0.94f * 20.0f;
  if (osa < 0) vysledek = -vysledek;
  return obratit ? -vysledek : vysledek;
}

inline bool lzeAktivovat(int plyn, float roll, float pitch, float cilRoll, float cilPitch) {
  return plyn <= 20 && fabsf(roll) < 15 && fabsf(pitch) < 15
         && fabsf(cilRoll) < 3 && fabsf(cilPitch) < 3;
}

// X konfigurace, pohled shora, predek nahore:
// M1 predni levy CCW     M2 predni pravy CW
// M4 zadni levy CW       M3 zadni pravy CCW
// +roll = prava strana dolu, +pitch = predek nahoru, +yaw = zataceni doprava.
// Korekce v mikrosekundach; yaw kladny zvysi CCW motory a snizi CW.
inline void smichejMotory(int plyn, float roll, float pitch, float yaw, uint16_t out[4]) {
  if (plyn <= 20) {  // Nulovy plyn vzdy zastavi vsechny vystupy.
    for (int i = 0; i < 4; i++) out[i] = 1000;
    return;
  }
  float zaklad = 1100.0f + (plyn - 21) * (700.0f / 1002.0f);
  float mix[4] = {roll + pitch + yaw, -roll + pitch - yaw,
                 -roll - pitch + yaw, roll - pitch - yaw};
  // Spolecny posun zakladu zachova rozdily pri dosazeni hranic vystupu.
  float minimum = mix[0], maximum = mix[0];
  for (int i = 1; i < 4; i++) {
    if (mix[i] < minimum) minimum = mix[i];
    if (mix[i] > maximum) maximum = mix[i];
  }
  zaklad = omez(zaklad, 1100.0f - minimum, 2000.0f - maximum);
  for (int i = 0; i < 4; i++) out[i] = static_cast<uint16_t>(omez(zaklad + mix[i], 1100, 2000));
}
