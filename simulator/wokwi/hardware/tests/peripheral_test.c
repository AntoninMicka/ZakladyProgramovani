// Test skutečných zdrojů obou nových chipů s malou náhradou Wokwi pin/timer API.
#define chip_init sensor_init
#include "../chips/sensor-front-end/sensor-front-end.chip.c"
#undef chip_init
#define chip_init outputs_init
#include "../chips/output-stage/output-stage.chip.c"
#undef chip_init
#include <assert.h>
#include <math.h>
#include <string.h>
static char names[128][32];
static unsigned count, levels[128];
static float volts[128];
static pin_watch_config_t watches[128];
static timer_config_t timer;
pin_t pin_init(const char *name, uint32_t mode) {
  unsigned i = count++;
  assert(i < 128);
  snprintf(names[i], sizeof(names[i]), "%s", name);
  levels[i] = mode == OUTPUT_HIGH || mode == INPUT_PULLUP;
  return i;
}
static pin_t find(const char *name) {
  for (unsigned i = 0; i < count; i++)
    if (!strcmp(names[i], name))
      return i;
  assert(false);
  return NO_PIN;
}
uint32_t pin_read(pin_t pin) {
  return levels[pin];
}
void pin_write(pin_t pin, uint32_t value) {
  unsigned previous = levels[pin];
  levels[pin] = value;
  if (previous != value && watches[pin].pin_change)
    watches[pin].pin_change(watches[pin].user_data, pin, value);
}
bool pin_watch(pin_t pin, const pin_watch_config_t *config) {
  watches[pin] = *config;
  return true;
}
float pin_adc_read(pin_t pin) {
  return volts[pin];
}
float pin_dac_write(pin_t pin, float value) {
  volts[pin] = value;
  return value;
}
timer_t timer_init(const timer_config_t *config) {
  timer = *config;
  return 1;
}
void timer_start(timer_t id, uint32_t interval, bool repeat) {
  assert(id == 1 && interval == 100 && repeat);
}
static void clear(void) {
  count = 0;
  memset(watches, 0, sizeof(watches));
  memset(volts, 0, sizeof(volts));
}
int main(void) {
  sensor_init();
  for (unsigned level = 0; level < 2; level++) {
    pin_write(find("CKP_IN"), level);
    pin_write(find("CMP_IN"), level);
    assert(pin_read(find("CKP_OUT")) == level);
    assert(pin_read(find("CMP_OUT")) == level);
  }
  const char *analog_names[] = {"MAP", "TPS", "IAT", "CLT", "LAMBDA"};
  for (unsigned i = 0; i < 5; i++) {
    char name[24];
    snprintf(name, sizeof(name), "%s_IN", analog_names[i]);
    volts[find(name)] = .3f + .5f * i;
  }
  timer.callback(timer.user_data);
  for (unsigned i = 0; i < 5; i++) {
    char name[24];
    snprintf(name, sizeof(name), "%s_OUT", analog_names[i]);
    assert(fabs(volts[find(name)] - (.3f + .5f * i)) < 1e-6);
  }
  clear();
  outputs_init();
  for (unsigned kind = 0; kind < 2; kind++) {
    unsigned active = kind ? OUTPUT_IGN_ACTIVE : OUTPUT_INJ_ACTIVE;
    for (unsigned i = 0; i < 4; i++) {
      char control[24], load[24];
      snprintf(control, sizeof(control), "%s%u_CTRL", kind ? "IGN" : "INJ", i + 1);
      snprintf(load, sizeof(load), "%s%u_LOAD", kind ? "IGN" : "INJ", i + 1);
      // Povel bez napájení zátěž nespustí.
      pin_write(find(control), active);
      assert(pin_read(find(load)) == !active);
      pin_write(find("POWER_EN"), HIGH);
      assert(pin_read(find(load)) == (i < OUTPUT_CYLINDERS ? active : !active));
      // Vypnutí napájení ukončí aktivitu i při stále aktivním povelu MCU.
      pin_write(find("POWER_EN"), LOW);
      assert(pin_read(find(load)) == !active);
      pin_write(find(control), !active);
      pin_write(find("POWER_EN"), HIGH);
      assert(pin_read(find(load)) == !active);
      pin_write(find("POWER_EN"), LOW);
    }
  }
  puts("PASS sensor edges, 5 ADC channels, 8 drivers, power-off gating and inactive outputs");
  return 0;
}
