// Výukový blok kabeláže a vstupů ECU. Signály jsou už upravené na úroveň MCU.
// Netvoří analogový model VR snímače, ochranných diod ani operačního zesilovače.
#include "../../../wokwi-api.h"
#include <stdio.h>
#include <stdlib.h>

typedef struct {
  pin_t digital_in[2], digital_out[2], analog_in[5], analog_out[5];
} front_end_t;
static void digital_change(void *user, pin_t pin, uint32_t value) {
  front_end_t *s = user;
  for (unsigned i = 0; i < 2; i++)
    if (pin == s->digital_in[i])
      pin_write(s->digital_out[i], value);
}
static void sample(void *user) {
  front_end_t *s = user;
  for (unsigned i = 0; i < 5; i++)
    pin_dac_write(s->analog_out[i], pin_adc_read(s->analog_in[i]));
}
void chip_init(void) {
  front_end_t *s = calloc(1, sizeof(*s));
  pin_init("VCC", INPUT);
  pin_init("GND", INPUT);
  const char *digital_names[] = {"CKP", "CMP"};
  const char *analog_names[] = {"MAP", "TPS", "IAT", "CLT", "LAMBDA"};
  for (unsigned i = 0; i < 2; i++) {
    char name[24];
    snprintf(name, sizeof(name), "%s_IN", digital_names[i]);
    s->digital_in[i] = pin_init(name, INPUT);
    snprintf(name, sizeof(name), "%s_OUT", digital_names[i]);
    s->digital_out[i] = pin_init(name, OUTPUT);
    pin_write(s->digital_out[i], pin_read(s->digital_in[i]));
    const pin_watch_config_t watch = {.user_data = s, .edge = BOTH, .pin_change = digital_change};
    pin_watch(s->digital_in[i], &watch);
  }
  for (unsigned i = 0; i < 5; i++) {
    char name[24];
    snprintf(name, sizeof(name), "%s_IN", analog_names[i]);
    s->analog_in[i] = pin_init(name, ANALOG);
    snprintf(name, sizeof(name), "%s_OUT", analog_names[i]);
    s->analog_out[i] = pin_init(name, ANALOG);
  }
  sample(s);
  const timer_config_t config = {.callback = sample, .user_data = s};
  timer_start(timer_init(&config), 100, true);
}
