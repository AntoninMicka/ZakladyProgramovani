// Wokwi vrstva: UART adaptér a piny jsou oddělené od hw_core i ECU firmware.
#include "../../../wokwi-api.h"
#include "adapter.h"
#include "../../config/generated_hw.h"
#include "hw_core.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef struct {
  hw_core_t core;
  adapter_t adapter;
  pin_t digital[2], analog[5], capture[2][4];
  uart_dev_t uart, diagnostic_uart;
  timer_t edge_timer, service_timer;
  bool busy;
  char diagnostic[160];
  unsigned diagnostic_used;
} chip_t;
static uint64_t now_us(void) {
  return get_sim_nanos() / 1000;
}
static void schedule(chip_t *s) {
  uint64_t deadline = hw_deadline(&s->core), now = now_us();
  timer_stop(s->edge_timer);
  if (deadline != HW_NEVER)
    timer_start_ns(s->edge_timer, (deadline > now ? deadline - now : 1) * 1000, false);
}
static void digital(void *user, unsigned signal, unsigned level) {
  chip_t *s = user;
  pin_write(s->digital[signal], level);
}
static void analog(void *user, unsigned index, double volts) {
  chip_t *s = user;
  pin_dac_write(s->analog[index], (float)volts);
}
static void event(void *user, const hw_event_t *e) {
  chip_t *s = user;
  adapter_event(&s->adapter, e);
}
static void edge_timer(void *user) {
  chip_t *s = user;
  hw_run(&s->core, now_us());
  schedule(s);
}
static void pump(chip_t *s) {
  const char *raw = adapter_output(&s->adapter);
  if (!s->busy && raw && uart_write(s->uart, (uint8_t *)raw, strlen(raw)))
    s->busy = true;
}
static void uart_done(void *user) {
  chip_t *s = user;
  s->busy = false;
  adapter_output_done(&s->adapter);
  pump(s);
}
static void receive(void *user, uint8_t byte) {
  chip_t *s = user;
  adapter_feed(&s->adapter, byte, now_us());
  schedule(s);
}
static void diagnostic(void *user, uint8_t byte) {
  chip_t *s = user;
  if (byte == '\n') {
    s->diagnostic[s->diagnostic_used] = 0;
    printf("ECU_DIAG %s\n", s->diagnostic);
    s->diagnostic_used = 0;
  } else if (s->diagnostic_used < sizeof(s->diagnostic) - 1)
    s->diagnostic[s->diagnostic_used++] = (char)byte;
}
static void capture(void *user, pin_t pin, uint32_t level) {
  chip_t *s = user;
  for (unsigned kind = 0; kind < 2; kind++)
    for (unsigned channel = 0; channel < 4; channel++)
      if (pin == s->capture[kind][channel]) {
        hw_capture(&s->core, kind, channel, level, now_us());
        schedule(s);
        return;
      }
}
static void service(void *user) {
  chip_t *s = user;
  static unsigned tick;
  // Samostatný timer pouze pro přenos/diagnostiku, ne generování GPIO hran.
  tick++;
  if (tick % 4 == 0)
    adapter_flush_events(&s->adapter);
  if (tick % 100 == 0)
    adapter_status(&s->adapter, now_us());
  pump(s);
}
void chip_init(void) {
  chip_t *s = calloc(1, sizeof(*s));
  s->digital[0] = pin_init("CKP", OUTPUT);
  s->digital[1] = pin_init("CMP", OUTPUT);
  const char *names[] = {"MAP", "TPS", "IAT", "CLT", "LAMBDA"};
  for (unsigned i = 0; i < 5; i++) {
    s->analog[i] = pin_init(names[i], ANALOG);
    pin_dac_write(s->analog[i], 0);
  }
  for (unsigned kind = 0; kind < 2; kind++)
    for (unsigned i = 0; i < 4; i++) {
      char name[8];
      snprintf(name, sizeof(name), "%s%u", kind ? "IGN" : "INJ", i + 1);
      s->capture[kind][i] = pin_init(name, INPUT);
    }
  hw_hooks_t hooks = {.user = s, .digital = digital, .analog = analog, .event = event};
  hw_init(&s->core, &HW_CONFIG, hooks, now_us());
  adapter_init(&s->adapter, &s->core);
  const uart_config_t uart = {.rx = pin_init("RX", INPUT),
                              .tx = pin_init("TX", INPUT_PULLUP),
                              .baud_rate = HW_UART_BAUD,
                              .rx_data = receive,
                              .write_done = uart_done,
                              .user_data = s};
  s->uart = uart_init(&uart);
  const uart_config_t diag = {.rx = pin_init("DIAG_RX", INPUT),
                              .tx = NO_PIN,
                              .baud_rate = HW_DIAG_BAUD,
                              .rx_data = diagnostic,
                              .user_data = s};
  s->diagnostic_uart = uart_init(&diag);
  const timer_config_t edge = {.callback = edge_timer, .user_data = s},
                       io = {.callback = service, .user_data = s};
  s->edge_timer = timer_init(&edge);
  s->service_timer = timer_init(&io);
  for (unsigned kind = 0; kind < 2; kind++)
    for (unsigned i = 0; i < 4; i++) {
      const pin_watch_config_t watch = {.edge = BOTH, .pin_change = capture, .user_data = s};
      pin_watch(s->capture[kind][i], &watch);
    }
  timer_start(s->service_timer, 1000, true);
  printf("ENGINE_INTERFACE_READY buffered/free; step-controlled unavailable\n");
}
