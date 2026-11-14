#pragma once
// Čas zůstává celočíselný i na AVR, kde double má pouze 32 bitů.
#include <ctype.h>
#include <errno.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

inline bool read_u32(const char *json, const char *key, uint32_t &value) {
  char pattern[64];
  snprintf(pattern, sizeof(pattern), "\"%s\"", key);
  const char *start = strstr(json, pattern);
  if (!start || !(start = strchr(start, ':')))
    return false;
  start++;
  while (isspace((unsigned char)*start))
    start++;
  if (!isdigit((unsigned char)*start))
    return false;
  errno = 0;
  char *end;
  unsigned long parsed = strtoul(start, &end, 10);
  if (errno == ERANGE || parsed > UINT32_MAX || end == start)
    return false;
  while (isspace((unsigned char)*end))
    end++;
  if (*end != ',' && *end != '}')
    return false;
  value = (uint32_t)parsed;
  return true;
}

struct LegacyTime {
  uint32_t host = 0, mcu = 0, epoch = 0, chip_origin = 0, mcu_origin = 0, last_chip = 0;
  double ratio = 1;
  bool anchored = false, chip_anchored = false;
  bool update(uint32_t new_host, uint32_t now, uint32_t new_epoch, double requested_speed) {
    bool reset = !anchored || new_epoch != epoch || (int32_t)(new_host - host) < 0;
    if (reset) {
      ratio = requested_speed;
      chip_anchored = false;
    } else if (now != mcu)
      ratio = (double)(new_host - host) / (uint32_t)(now - mcu);
    host = new_host;
    mcu = now;
    epoch = new_epoch;
    anchored = true;
    return reset;
  }
  uint32_t map(uint32_t raw, uint32_t now) {
    if (!chip_anchored || (int32_t)(raw - last_chip) < 0) {
      chip_origin = raw;
      mcu_origin = now;
      chip_anchored = true;
    }
    last_chip = raw;
    int32_t delta = (int32_t)(mcu_origin + (uint32_t)(raw - chip_origin) - mcu);
    // Sčítání absolutního času musí být integer, nikoliv AVR float.
    int64_t result = (int64_t)host + (int32_t)lround(delta * ratio);
    return result < 0 ? 0 : result > UINT32_MAX ? UINT32_MAX : (uint32_t)result;
  }
};

struct LegacyPulse {
  bool active = false;
  uint32_t raw_start = 0, host_start = 0;
  double ratio = 1;
  void start(uint32_t raw, uint32_t mapped, double speed) {
    active = true;
    raw_start = raw;
    host_start = mapped;
    ratio = speed;
  }
  bool end(uint32_t raw, uint32_t &mapped, uint32_t &duration) {
    if (!active)
      return false;
    active = false;
    duration = raw - raw_start;
    if (duration > 50000)
      return false;
    mapped = host_start + (uint32_t)lround(duration * ratio);
    return true;
  }
};
