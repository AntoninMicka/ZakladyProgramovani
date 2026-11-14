#ifndef ECU_HW_CORE_H
#define ECU_HW_CORE_H
#include <stdbool.h>
#include <stdint.h>
#define HW_CHANNELS 4
#define HW_MAX_CMP 8
#define HW_MAX_POINTS 16
#define HW_QUEUE 64
#define HW_NEVER UINT64_MAX

typedef struct {
  unsigned count;
  double x[HW_MAX_POINTS], v[HW_MAX_POINTS];
} hw_curve_t;
typedef struct {
  unsigned cylinders, injectors, ignitions, teeth, missing, cmp_count;
  bool ckp_high, cmp_high, injector_high, ignition_high, cmp_stuck;
  double duty, cmp_positions[HW_MAX_CMP], cmp_width, cmp_offset;
  int skip_tooth;
  double noise_angle, noise_width;
  uint64_t max_pulse_us, watchdog_us;
  hw_curve_t analog[5];
} hw_config_t;
typedef struct {
  uint64_t apply_us, simulation_us;
  double rpm, cycle_angle, sensors[5];
} hw_state_t;
typedef struct {
  uint64_t time_us, simulation_us, duration_us;
  unsigned kind, channel, action, error;
  double angle;
} hw_event_t;
// action 0=start/charge, 1=end/spark, 2=aborted, 3=invalid, 4=timeout.
// error 1=duplicate start, 2=unpaired end, 3=reset/link loss, 4=timeout, 5=unmapped clock.
typedef struct {
  void *user;
  void (*digital)(void *, unsigned, unsigned);
  void (*analog)(void *, unsigned, double);
  void (*event)(void *, const hw_event_t *);
} hw_hooks_t;
typedef struct {
  const hw_config_t *cfg;
  hw_hooks_t hooks;
  uint64_t now_us, last_apply_us, origin_local_us, origin_sim_us;
  double angle, rpm, phase_error;
  bool running, mapped, buffered;
  unsigned level[2], queued;
  hw_state_t queue[HW_QUEUE];
  bool active[2][HW_CHANNELS];
  uint64_t starts[2][HW_CHANNELS];
  uint32_t late, overflows, timeouts, invalid_pulses, underruns;
} hw_core_t;
void hw_init(hw_core_t *, const hw_config_t *, hw_hooks_t, uint64_t);
void hw_reset(hw_core_t *, uint64_t);
bool hw_enqueue(hw_core_t *, const hw_state_t *, uint64_t, bool);
void hw_run(hw_core_t *, uint64_t);
uint64_t hw_deadline(const hw_core_t *);
void hw_capture(hw_core_t *, unsigned, unsigned, unsigned, uint64_t);
double hw_voltage(const hw_curve_t *, double);
#endif
