// Adaptér pro počítač. Rozhodování zůstává ve STEJNÉM ecu_controller.h jako na desce.
#include "ecu_controller.h"
#include <cstddef>
#include <cstdint>
#include <new>

struct InputEdge {
  uint64_t time;
  uint32_t signal, level;
};
struct OutputEdge {
  uint64_t time, duration;
  uint32_t kind, channel, active;
  double advance;
};
struct HostEcu {
  EcuController ecu;
  uint64_t now = 0, next_tick = ECU_TIMER_US;
  uint64_t starts[2][ECU_CYLINDERS] = {};
  bool pins[2][ECU_CYLINDERS] = {};
};
extern "C" {
void *ecu_create() {
  return new (std::nothrow) HostEcu;
}
void ecu_destroy(HostEcu *host) {
  delete host;
}
void ecu_reset(HostEcu *host, uint64_t now, double accelerator) {
  *host = HostEcu{};
  host->now = now;
  host->next_tick = now + ECU_TIMER_US;
  host->ecu.set_accelerator(accelerator);
  host->ecu.update_control(static_cast<uint32_t>(now));
  host->ecu.last_control_us = static_cast<uint32_t>(now);
  host->ecu.have_control = true;
}
// Čas je výhradně simulační. Při shodném čase obsloužíme snímač před časovačem.
int ecu_advance(HostEcu *host, uint64_t end, double accelerator, const InputEdge *edges,
                size_t count, OutputEdge *outputs, size_t capacity) {
  if (end < host->now)
    return -1;
  for (size_t i = 0; i < count; i++)
    if (edges[i].time < host->now || edges[i].time > end ||
        (i && edges[i].time < edges[i - 1].time) || edges[i].signal > 1 || edges[i].level > 1)
      return -1;
  host->ecu.set_accelerator(accelerator);
  size_t input = 0, output = 0;
  bool overflow = false;
  auto write = [&](bool ignition, unsigned channel, unsigned level) {
    bool active = level == (ignition ? ECU_IGN_ACTIVE : ECU_INJ_ACTIVE);
    if (host->pins[ignition][channel] == active)
      return;
    host->pins[ignition][channel] = active;
    if (active)
      host->starts[ignition][channel] = host->now;
    if (output == capacity) {
      overflow = true;
      return;
    }
    // Měření polohy jiskry pro zpětnou vazbu do fyzikálního modelu.
    unsigned order = 0;
    while (order < ECU_CYLINDERS && FIRING_ORDER[order] != channel + 1)
      order++;
    double phase = EcuController::wrap(host->ecu.phase_at_edge +
                                       (static_cast<uint32_t>(host->now) - host->ecu.last_ckp) * 6 *
                                           host->ecu.rpm / 1e6);
    double advance = fmod(order * 720.0 / ECU_CYLINDERS - phase + 1080, 720) - 360;
    outputs[output++] = {host->now,
                         active ? 0 : host->now - host->starts[ignition][channel],
                         static_cast<uint32_t>(ignition),
                         channel,
                         static_cast<uint32_t>(active),
                         advance};
  };
  while (host->next_tick <= end || input < count) {
    uint64_t next = input < count ? edges[input].time : host->next_tick;
    if (host->next_tick < next)
      next = host->next_tick;
    host->now = next;
    while (input < count && edges[input].time == next) {
      const auto &edge = edges[input++];
      // Python generuje logické aktivní hrany. Elektrickou polaritu zde nepotřebuje.
      if (edge.level) {
        if (edge.signal)
          host->ecu.cam(static_cast<uint32_t>(next));
        else
          host->ecu.crank(static_cast<uint32_t>(next));
      }
    }
    if (host->next_tick == next) {
      host->ecu.tick(static_cast<uint32_t>(next), write);
      host->next_tick += ECU_TIMER_US;
    }
  }
  host->now = end;
  return overflow ? -2 : static_cast<int>(output);
}
double ecu_requested_rpm(const HostEcu *host) {
  return host->ecu.requested_rpm;
}
double ecu_pedal(const HostEcu *host) {
  return host->ecu.accelerator;
}
uint32_t ecu_injection_us(const HostEcu *host) {
  return host->ecu.injection_us;
}
double ecu_rpm(const HostEcu *host) {
  return host->ecu.rpm;
}
unsigned ecu_synced(const HostEcu *host) {
  return host->ecu.synced;
}
uint32_t ecu_errors(const HostEcu *host) {
  return host->ecu.errors;
}
}
