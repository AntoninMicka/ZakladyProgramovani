// Hostitelske testy vypoctu: g++ -std=c++11 tests/controller_test.cpp -o /tmp/quad_test
#include "../src/controller.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>

int main() {
  assert(pozadavekOsy(512) == 0);
  assert(pozadavekOsy(500) == 0);
  assert(fabsf(pozadavekOsy(1023) - 20) < 0.001f);
  assert(fabsf(pozadavekOsy(0) + 20) < 0.001f);
  assert(pozadavekOsy(0, true) > 19.9f);
  assert(lzeAktivovat(0, 0, 0, 0, 0));
  assert(!lzeAktivovat(21, 0, 0, 0, 0));
  assert(!lzeAktivovat(0, 15, 0, 0, 0));
  assert(!lzeAktivovat(0, 0, 0, 4, 0));
  uint16_t m[4];
  smichejMotory(0, 120, -120, 80, m);
  for (int i = 0; i < 4; i++) assert(m[i] == 1000);
  smichejMotory(512, 0, 0, 0, m);
  for (int i = 1; i < 4; i++) assert(m[i] == m[0]);
  smichejMotory(512, 100, 0, 0, m);  // +roll zvysi levou dvojici.
  assert(m[0] == m[3] && m[1] == m[2] && m[0] > m[1]);
  smichejMotory(512, 0, 100, 0, m);  // +pitch zvysi predni dvojici.
  assert(m[0] == m[1] && m[2] == m[3] && m[0] > m[2]);
  smichejMotory(512, 0, 0, 80, m);  // +yaw zvysi CCW dvojici.
  assert(m[0] == m[2] && m[1] == m[3] && m[0] > m[1]);
  // Overeni hranic a zachovani rozdilu i pri saturaci spolecneho plynu.
  for (int plyn = 21; plyn <= 1023; plyn++) {
    for (int r = -120; r <= 120; r += 120) {
      for (int p = -120; p <= 120; p += 120) {
        for (int y = -80; y <= 80; y += 80) {
          smichejMotory(plyn, r, p, y, m);
          for (int i = 0; i < 4; i++) assert(m[i] >= 1100 && m[i] <= 2000);
          assert(abs(static_cast<int>(m[0]) - m[1] - 2 * (r + y)) <= 1);
        }
      }
    }
  }
  puts("OK: joystick, ARM podminky, STOP, symetrie, smer korekci a saturace mixeru.");
}
