#include "../chips/engine-interface/hw_core.h"
#include "../config/generated_hw.h"
#include <assert.h>
#include <math.h>
#include <stdio.h>
#include <string.h>

typedef struct {
  uint64_t t;
  unsigned signal, level;
} edge_t;
static hw_core_t core;
static edge_t edges[20000];
static unsigned edge_count, event_count;
static hw_event_t events[128];
static double analogs[5];
static void digital(void *user, unsigned signal, unsigned value) {
  hw_core_t *s = user;
  assert(edge_count < 20000);
  edges[edge_count++] = (edge_t){s->now_us, signal, value};
}
static void analog(void *user, unsigned index, double voltage) {
  (void)user;
  analogs[index] = voltage;
}
static void event(void *user, const hw_event_t *e) {
  (void)user;
  assert(event_count < 128);
  events[event_count++] = *e;
}
static void init(const hw_config_t *cfg) {
  edge_count = event_count = 0;
  memset(analogs, 0, sizeof(analogs));
  hw_init(&core, cfg, (hw_hooks_t){&core, digital, analog, event}, 0);
  edge_count = 0;
}
static hw_state_t state(uint64_t time, double rpm, double angle) {
  return (hw_state_t){.apply_us = time,
                      .simulation_us = time + 100000,
                      .rpm = rpm,
                      .cycle_angle = angle,
                      .sensors = {100, .5, 25, 85, 1}};
}
static void run_until(uint64_t target) {
  unsigned iterations = 0;
  while (hw_deadline(&core) <= target) {
    uint64_t time = hw_deadline(&core);
    assert(time >= core.now_us);
    hw_run(&core, time);
    assert(hw_deadline(&core) > time);
    assert(++iterations < 100000);
  }
  hw_run(&core, target);
}
static unsigned count(unsigned signal, unsigned level) {
  unsigned n = 0;
  for (unsigned i = 0; i < edge_count; i++)
    if (edges[i].signal == signal && edges[i].level == level)
      n++;
  return n;
}
int main(void) {
  init(&HW_CONFIG);
  hw_state_t s = state(1000, 1000, 0);
  assert(hw_enqueue(&core, &s, 0, true));
  run_until(121000);
  assert(count(0, 1) == 117);
  assert(count(1, 1) == 2);
  uint64_t previous = 0;
  unsigned missing = 0;
  for (unsigned i = 0; i < edge_count; i++)
    if (!edges[i].signal && edges[i].level) {
      if (previous) {
        uint64_t gap = edges[i].t - previous;
        assert(gap == 1000 || gap == 3000);
        if (gap == 3000)
          missing++;
      }
      previous = edges[i].t;
    }
  assert(missing == 2);
  assert(fabs(analogs[0] - 1.188) < 1e-8);
  assert(fabs(analogs[1] - 1.65) < 1e-8);
  assert(fabs(analogs[2] - 1.65) < 1e-8);
  assert(analogs[3] < 1.65);
  puts("PASS constant 60-2 / CMP 720 / analog LUT+NTC");

  // Doručení druhého stavu dříve/později před stejným apply time nemění GPIO hrany.
  static edge_t reference[20000];
  unsigned reference_count;
  init(&HW_CONFIG);
  s = state(1000, 1000, 0);
  hw_enqueue(&core, &s, 0, true);
  s = state(61000, 2000, 360);
  hw_enqueue(&core, &s, 0, true);
  run_until(100000);
  reference_count = edge_count;
  memcpy(reference, edges, edge_count * sizeof(edge_t));
  init(&HW_CONFIG);
  s = state(1000, 1000, 0);
  hw_enqueue(&core, &s, 0, true);
  run_until(50000);
  s = state(61000, 2000, 360);
  hw_enqueue(&core, &s, 50000, true);
  run_until(100000);
  assert(edge_count == reference_count);
  for (unsigned i = 0; i < edge_count; i++)
    assert(reference[i].t == edges[i].t && reference[i].signal == edges[i].signal &&
           reference[i].level == edges[i].level);
  puts("PASS buffered GPIO timing independent of early UART arrival");

  init(&HW_CONFIG);
  s = state(1000, 1000, 0);
  assert(hw_enqueue(&core, &s, 0, true));
  s = state(61000, 2000, 360);
  assert(hw_enqueue(&core, &s, 0, true));
  s = state(91000, 500, 0);
  s.sensors[1] = .8;
  s.sensors[2] = 40;
  assert(hw_enqueue(&core, &s, 0, true));
  run_until(151000);
  bool fast = false, slow = false;
  previous = 0;
  for (unsigned i = 0; i < edge_count; i++)
    if (!edges[i].signal && edges[i].level) {
      uint64_t gap = edges[i].t - previous;
      if (previous && edges[i].t > 62000 && edges[i].t < 90000 && gap == 500)
        fast = true;
      if (previous && edges[i].t > 95000 && gap == 2000)
        slow = true;
      previous = edges[i].t;
    }
  assert(fast && slow);
  assert(fabs(analogs[1] - 2.442) < 1e-8);
  assert(fabs(analogs[2] - 1.14334402033) < 1e-8);
  puts("PASS acceleration and deceleration at buffered deadlines");

  init(&HW_CONFIG);
  s = state(1000, 1000, 0);
  hw_enqueue(&core, &s, 0, true);
  s = state(10000, 0, 54);
  hw_enqueue(&core, &s, 0, true);
  run_until(10000);
  unsigned stopped = edge_count;
  run_until(20000);
  assert(edge_count == stopped);
  assert(core.level[0] == 0 && core.level[1] == 0);
  s = state(21000, 1000, 54);
  hw_enqueue(&core, &s, 20000, true);
  run_until(30000);
  assert(edge_count > stopped);
  puts("PASS stop and restart");

  hw_capture(&core, 0, 2, 1, 31000);
  hw_capture(&core, 0, 2, 0, 34500);
  assert(events[1].duration_us == 3500 && events[1].channel == 2 && events[1].action == 1);
  hw_capture(&core, 1, 1, 1, 35000);
  hw_capture(&core, 1, 1, 0, 37000);
  assert(events[3].duration_us == 2000 && events[3].kind == 1 && events[3].angle > 0);
  hw_capture(&core, 0, 0, 0, 38000);
  assert(events[4].error == 2);
  hw_capture(&core, 0, 0, 1, 39000);
  hw_capture(&core, 0, 0, 1, 40000);
  assert(events[6].error == 1);
  hw_reset(&core, 41000);
  assert(events[7].action == 2 && !core.active[0][0]);
  assert(core.queued == 0 && !core.running);
  puts("PASS injector / dwell / spark angle / malformed and reset pulses");

  init(&HW_CONFIG);
  s = state(1000, 1000, 0);
  hw_enqueue(&core, &s, 0, true);
  run_until(2000);
  hw_capture(&core, 0, 0, 1, 2000);
  run_until(52000);
  assert(events[1].action == 4);
  run_until(1001000);
  assert(!core.running && core.timeouts == 1);
  s = state(900000, 1000, 0);
  assert(!hw_enqueue(&core, &s, 1001000, true));
  assert(core.late == 1);
  puts("PASS incomplete pulse timeout / link watchdog / late state rejection");

  init(&HW_CONFIG);
  for (unsigned i = 0; i < 64; i++) {
    s = state(1000 + i * 1000, 1000, 0);
    assert(hw_enqueue(&core, &s, 0, true));
  }
  s = state(100000, 1000, 0);
  assert(!hw_enqueue(&core, &s, 0, true));
  assert(core.overflows == 1);
  puts("PASS bounded buffered queue");

  hw_config_t cfg = HW_CONFIG;
  cfg.ckp_high = false;
  cfg.cmp_high = false;
  cfg.skip_tooth = 4;
  cfg.cmp_count = 2;
  cfg.cmp_positions[1] = 420;
  init(&cfg);
  s = state(1000, 1000, 0);
  hw_enqueue(&core, &s, 0, true);
  run_until(121000);
  assert(count(0, 0) == 115);
  assert(count(1, 0) == 3);
  cfg = HW_CONFIG;
  cfg.noise_angle = 350;
  cfg.noise_width = 1;
  init(&cfg);
  s = state(1000, 1000, 0);
  hw_enqueue(&core, &s, 0, true);
  run_until(121000);
  assert(count(0, 1) == 119);
  cfg.cmp_high = false;
  cfg.cmp_stuck = true;
  init(&cfg);
  s = state(1000, 1000, 0);
  hw_enqueue(&core, &s, 0, true);
  run_until(121000);
  assert(count(1, 0) == 0);
  cfg = HW_CONFIG;
  cfg.cmp_offset = 20;
  cfg.duty = .25;
  init(&cfg);
  s = state(1000, 1000, 0);
  hw_enqueue(&core, &s, 0, true);
  run_until(10000);
  bool shifted = false, narrow = false;
  for (unsigned i = 0; i < edge_count; i++) {
    if (edges[i].signal == 1 && edges[i].level == 1 && edges[i].t == 4334)
      shifted = true;
    if (edges[i].signal == 0 && edges[i].level == 0 && edges[i].t == 1250)
      narrow = true;
  }
  assert(shifted && narrow);
  puts("PASS configurable polarity / missing fault / multi-CMP / CMP fault");
  return 0;
}
