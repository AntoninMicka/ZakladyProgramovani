// Model omezené UART: 10 bitů na bajt, skutečné serializované rámce, virtuální čas.
#include "../chips/engine-interface/adapter.h"
#include "../config/generated_hw.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
static hw_core_t core;
static adapter_t adapter;
static void digital(void *u, unsigned s, unsigned v) {
  (void)u;
  (void)s;
  (void)v;
}
static void analog(void *u, unsigned s, double v) {
  (void)u;
  (void)s;
  (void)v;
}
static void event(void *u, const hw_event_t *e) {
  (void)u;
  (void)e;
}
// Reálná chráněná hostitelská zpráva vyvolá clock_sync odpověď při 20 Hz.
static void host_state(unsigned now) {
  char raw[1024];
  snprintf(raw, sizeof(raw),
           "{\"version\":1,\"type\":\"engine_state\",\"source\":\"host\","
           "\"sequence\":%u,\"simulation_time_us\":%llu,\"data\":{"
           "\"rpm\":0,\"cycle_angle_deg\":0,\"map_kpa\":40,\"iat_c\":25,"
           "\"clt_c\":85,\"tps\":0.35,\"lambda_value\":1,\"hardware\":{"
           "\"session\":1234567890,\"mode\":\"free\",\"lookahead_us\":100000}},\"error\":null}",
           now / 50000 + 1, (unsigned long long)(1000000000000ull + now));
  assert(json_protect(raw, sizeof(raw)));
  for (const char *p = raw; *p; p++)
    adapter_feed(&adapter, (uint8_t)*p, now);
  hw_run(&core, now);
}
static void run(unsigned rpm) {
  hw_init(&core, &HW_CONFIG, (hw_hooks_t){NULL, digital, analog, event}, 0);
  adapter_init(&adapter, &core);
  adapter.session = 1234567890;
  unsigned generated = 0, frames = 0, bytes = 0, peak = 0;
  double wire_done = 0;
  bool busy = false;
  const unsigned duration_us = 10000000;
  for (unsigned now = 0; now <= duration_us; now += 10) {
    if (now % 50000 == 0)
      host_state(now);
    unsigned target = (unsigned)((uint64_t)now * rpm * 16 / 120000000);
    while (generated < target) {
      unsigned n = generated % 16;
      hw_event_t e = {.time_us = 1000000000000ull + now,
                      .simulation_us = 1000000000000ull + now,
                      .kind = n / 8,
                      .channel = n % 8 / 2,
                      .action = n % 2,
                      .duration_us = n % 2 ? 3000 : 0,
                      .angle = 719.999};
      adapter_event(&adapter, &e);
      generated++;
    }
    if (now % 4000 == 0)
      adapter_flush_events(&adapter);
    if (now % 100000 == 0)
      adapter_status(&adapter, now);
    unsigned depth = (adapter.head + ADAPTER_TX_QUEUE - adapter.tail) % ADAPTER_TX_QUEUE;
    if (depth > peak)
      peak = depth;
    if (busy && now >= wire_done) {
      adapter_output_done(&adapter);
      busy = false;
    }
    const char *out = adapter_output(&adapter);
    if (!busy && out) {
      unsigned size = (unsigned)strlen(out);
      assert(size < ADAPTER_TX_FRAME);
      wire_done = now + size * 10.0 * 1000000 / HW_UART_BAUD;
      busy = true;
      frames++;
      bytes += size;
    }
  }
  assert(adapter.received == 201);
  assert(adapter.dropped == 0);
  assert(peak < 8);
  double utilization = bytes * 10.0 / (HW_UART_BAUD * (duration_us / 1e6));
  assert(utilization < .8);
  printf("PASS %u RPM: events=%u frames=%u bytes/s=%.0f utilization=%.1f%% peak=%u dropped=%u\n",
         rpm, generated, frames, bytes / (duration_us / 1e6), 100 * utilization, peak,
         adapter.dropped);
}
int main(void) {
  run(2000);
  run(7500);
  return 0;
}
