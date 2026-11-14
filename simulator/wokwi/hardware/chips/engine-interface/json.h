#ifndef ECU_JSON_H
#define ECU_JSON_H
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#define JSON_TOKENS 384
typedef struct {
  int start, end, parent;
  char type;
} json_token_t;
typedef struct {
  const char *text;
  int length, count;
  json_token_t token[JSON_TOKENS];
} json_doc_t;
bool json_parse(json_doc_t *, const char *, size_t);
int json_get(const json_doc_t *, int, const char *);
bool json_number(const json_doc_t *, int, double *);
bool json_equal(const json_doc_t *, int, const char *);
uint32_t json_crc32(const char *, size_t);
bool json_integrity(const json_doc_t *);
size_t json_protect(char *, size_t);
#endif
