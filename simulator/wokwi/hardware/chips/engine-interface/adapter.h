#ifndef ECU_ADAPTER_H
#define ECU_ADAPTER_H
#include "hw_core.h"
#include "json.h"
#define ADAPTER_TX_QUEUE 128
#define ADAPTER_FRAME 16384
#define ADAPTER_TX_FRAME 2048
#define ADAPTER_EVENT_BATCH 16
typedef struct {
  hw_core_t *core;
  char input[ADAPTER_FRAME], output[ADAPTER_TX_QUEUE][ADAPTER_TX_FRAME];
  unsigned used, head, tail;
  bool discard, session_set, have_sequence;
  uint32_t session;
  uint64_t sequence, last_sequence, origin_host, origin_local, last_host;
  uint32_t received, invalid, crc_errors, stale, dropped, resets;
  hw_event_t events[ADAPTER_EVENT_BATCH];
  unsigned event_count;
  json_doc_t doc;
} adapter_t;
void adapter_init(adapter_t *, hw_core_t *);
void adapter_feed(adapter_t *, uint8_t, uint64_t);
void adapter_event(adapter_t *, const hw_event_t *);
void adapter_flush_events(adapter_t *);
void adapter_status(adapter_t *, uint64_t);
const char *adapter_output(adapter_t *);
void adapter_output_done(adapter_t *);
#endif
