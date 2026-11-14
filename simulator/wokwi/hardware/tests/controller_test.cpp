// Skutečná řídicí logika firmware + stejné hw_core: integrace virtuálních GPIO bez Wokwi runtime.
#include "../firmware/include/ecu_controller.h"
#include <cassert>
#include <cmath>
#include <cstdio>
extern "C" {
#include "../chips/engine-interface/hw_core.h"
const hw_config_t *test_config(void);
}
static hw_core_t core;
static EcuController ecu;
static unsigned levels[2], ends[2][4], starts[2][4];
static bool pins[2][4];
static void digital(void *u, unsigned signal, unsigned value) {
  (void)u;
  unsigned previous = levels[signal];
  levels[signal] = value;
  if (previous == value)
    return;
  if (!signal && value == ECU_CKP_ACTIVE)
    ecu.crank((uint32_t)core.now_us);
  if (signal && value == ECU_CMP_ACTIVE)
    ecu.cam((uint32_t)core.now_us);
}
static void analog(void *u, unsigned i, double value) {
  (void)u;
  (void)i;
  assert(value >= 0 && value <= 5);
}
static void event(void *u, const hw_event_t *e) {
  (void)u;
  assert(!e->error);
  if (!e->action)
    starts[e->kind][e->channel]++;
  if (e->action == 1) {
    ends[e->kind][e->channel]++;
    uint64_t expected = e->kind ? ECU_DWELL_US : ECU_INJECTION_US;
    assert(e->duration_us >= expected && e->duration_us <= expected + ECU_TIMER_US);
    assert(e->angle >= 0 && e->angle < 720);
    if (e->kind) {
      unsigned order = 0;
      while (FIRING_ORDER[order] != e->channel + 1)
        order++;
      double target = EcuController::wrap(order * 720.0 / ECU_CYLINDERS - ECU_ADVANCE_DEG);
      double error = fabs(fmod(e->angle - target + 1080, 720) - 360);
      assert(error <= .4); // 25 µs ISR krok při 1000 RPM, bez Wokwi CPU latence
    }
  }
}
static void write(bool ignition, unsigned channel, unsigned value) {
  pins[ignition][channel] = value;
  hw_capture(&core, ignition, channel, value, core.now_us);
}
int main(void) {
  hw_init(&core, test_config(), (hw_hooks_t){NULL, digital, analog, event}, 0);
  uint64_t tick = ECU_TIMER_US, update = 0;
  while (core.now_us < 2000000) {
    uint64_t next = hw_deadline(&core);
    if (tick < next)
      next = tick;
    if (update < next)
      next = update;
    hw_run(&core, next);
    if (next == update) {
      hw_state_t state = {};
      state.apply_us = next + 100000;
      state.simulation_us = next;
      state.rpm = 1000;
      state.cycle_angle = fmod(next * .006, 720);
      const double sensors[] = {100, .5, 25, 85, 1};
      for (int i = 0; i < 5; i++)
        state.sensors[i] = sensors[i];
      assert(hw_enqueue(&core, &state, next, true));
      update += 50000;
    }
    if (next == tick) {
      ecu.tick((uint32_t)tick, write);
      tick += ECU_TIMER_US;
    }
  }
  assert(ecu.synced);
  assert(fabs(ecu.rpm - 1000) < 2);
  for (unsigned kind = 0; kind < 2; kind++)
    for (unsigned ch = 0; ch < ECU_CYLINDERS; ch++) {
      assert(starts[kind][ch] > 5);
      assert(ends[kind][ch] > 5);
    }
  puts("PASS CKP-derived RPM, CMP phase, 4 sequential injectors and independent coils");
  // Po výpadku hostitele doběhne ohraničený buffer/watchdog, ECU detekuje chybějící CKP.
  while (core.now_us < 3200000) {
    uint64_t next = hw_deadline(&core);
    if (tick < next)
      next = tick;
    hw_run(&core, next);
    if (next == tick) {
      ecu.tick((uint32_t)tick, write);
      tick += ECU_TIMER_US;
    }
  }
  assert(!core.running && !ecu.synced);
  for (unsigned ch = 0; ch < 4; ch++)
    assert(!pins[0][ch] && !pins[1][ch]);
  puts("PASS watchdog and ECU output shutdown");
  return 0;
}
