// Blok MOSFET/IGBT driverů a zátěží: ověřuje logické sepnutí, nikoli proud či 12 V.
// GPIO MCU je řídicí vstup. Do engine-interface se vrací stav zátěže ZA driverem.
#include "../../../wokwi-api.h"
#include "../../config/generated_outputs.h"
#include <stdio.h>
#include <stdlib.h>

typedef struct {
  pin_t enable, command[2][4], load[2][4];
} output_stage_t;
static void refresh(void *user, pin_t pin, uint32_t value) {
  (void)pin;
  (void)value;
  output_stage_t *s = user;
  bool powered = pin_read(s->enable) != 0;
  for (unsigned kind = 0; kind < 2; kind++) {
    unsigned active_level = kind ? OUTPUT_IGN_ACTIVE : OUTPUT_INJ_ACTIVE;
    for (unsigned i = 0; i < 4; i++) {
      bool active =
          powered && i < OUTPUT_CYLINDERS && pin_read(s->command[kind][i]) == active_level;
      // Capture zachovává polaritu z konfigurace. Kontrolka je připojena podle polarity.
      pin_write(s->load[kind][i], active ? active_level : !active_level);
    }
  }
}
void chip_init(void) {
  output_stage_t *s = calloc(1, sizeof(*s));
  pin_init("VCC", INPUT);
  pin_init("PGND", INPUT);
  s->enable = pin_init("POWER_EN", INPUT_PULLDOWN);
  const pin_watch_config_t watch = {.user_data = s, .edge = BOTH, .pin_change = refresh};
  for (unsigned kind = 0; kind < 2; kind++) {
    unsigned active_level = kind ? OUTPUT_IGN_ACTIVE : OUTPUT_INJ_ACTIVE;
    for (unsigned i = 0; i < 4; i++) {
      char name[24];
      snprintf(name, sizeof(name), "%s%u_CTRL", kind ? "IGN" : "INJ", i + 1);
      s->command[kind][i] = pin_init(name, active_level ? INPUT_PULLDOWN : INPUT_PULLUP);
      snprintf(name, sizeof(name), "%s%u_LOAD", kind ? "IGN" : "INJ", i + 1);
      s->load[kind][i] = pin_init(name, active_level ? OUTPUT_LOW : OUTPUT_HIGH);
      pin_watch(s->command[kind][i], &watch);
    }
  }
  pin_watch(s->enable, &watch);
  refresh(s, NO_PIN, 0);
}
