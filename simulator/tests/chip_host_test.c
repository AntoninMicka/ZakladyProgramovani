// Testuje skutečný zdroj chipu s náhradami API; není to běh ve Wokwi.
#include "../wokwi/engine-signals.chip.c"
#include <assert.h>
#include <stdio.h>
#include <string.h>
static uint64_t nanos;
static unsigned count;
static char names[32][16];
static uint32_t levels[32];
static float volts[32];
static pin_watch_config_t watches[32];
static timer_config_t timer;
static uart_config_t uart;
static unsigned ckp_rises, cmp_rises;
static uint64_t last_rise, max_gap;
static char transmitted[100];

pin_t pin_init(const char *name, uint32_t mode) {
  strcpy(names[count], name);
  levels[count] = mode == OUTPUT_HIGH;
  return count++;
}
void pin_write(pin_t pin, uint32_t value) {
  if (value && !levels[pin]) {
    if (strcmp(names[pin], "CKP") == 0) {
      ++ckp_rises;
      if (last_rise && nanos - last_rise > max_gap)
        max_gap = nanos - last_rise;
      last_rise = nanos;
    }
    if (strcmp(names[pin], "CMP") == 0)
      ++cmp_rises;
  }
  levels[pin] = value;
}
float pin_dac_write(pin_t pin, float voltage) {
  volts[pin] = voltage;
  return voltage;
}
bool pin_watch(pin_t pin, const pin_watch_config_t *config) {
  watches[pin] = *config;
  return true;
}
uart_dev_t uart_init(const uart_config_t *config) {
  uart = *config;
  return 1;
}
bool uart_write(uart_dev_t id, uint8_t *buffer, uint32_t size) {
  (void)id;
  assert(size < sizeof(transmitted));
  memcpy(transmitted, buffer, size);
  transmitted[size] = 0;
  return true;
}
timer_t timer_init(const timer_config_t *config) {
  timer = *config;
  return 1;
}
void timer_start(timer_t id, uint32_t micros, bool repeat) {
  (void)id;
  assert(micros == 10);
  assert(repeat);
}
double get_sim_nanos_d(void) {
  return nanos;
}
void timer_start_ns_d(timer_t id, double delay, bool repeat) {
  (void)id;
  (void)delay;
  (void)repeat;
}
static void input(const char *s) {
  for (; *s; s++)
    uart.rx_data(uart.user_data, *s);
}
static void advance(uint64_t until) {
  while (nanos < until) {
    nanos += 10000;
    timer.callback(timer.user_data);
  }
}
int main(void) {
  chip_init();
  chip_state_t *s = timer.user_data;
  input("S 100000 10000 50 2500 8500 100\n");
  assert(s->rpm == 1000);
  assert(fabs(volts[s->analog[0]] - 2.5) < .001);
  assert(fabs(volts[s->analog[1]] - 2.5) < .001);
  advance(120000000);
  assert(ckp_rises == 116);
  assert(cmp_rises == 1); // počáteční HIGH není nová hrana
  assert(max_gap >= 2990000 && max_gap <= 3010000);
  // Událost nese čas zdroje, nikoli čas UART doručení.
  watches[s->injector[2]].pin_change(s, s->injector[2], 1);
  advance(nanos + 10000);
  assert(strstr(transmitted, "E 120000 0 2 1") != NULL);
  uart.write_done(s);
  input("S 200000 10000 50 2500 8500 100\n");
  unsigned before = ckp_rises;
  advance(180010000);
  assert(ckp_rises - before == 116);
  input("S 0 0 0 0 0 0\n");
  double angle = s->angle;
  advance(200000000);
  assert(s->angle == angle);
  for (int i = 0; i < 100; i++)
    on_rx(s, 'x');
  on_rx(s, '\n');
  assert(!s->discard && s->used == 0);
  puts("chip host test: 60-2, CMP, RPM changes, capture, analog and bounds OK");
  free(s);
  return 0;
}
