// Stejná vstupní kalibrace a výpočet paliva jako ve firmware i Mock.
#include "../firmware/include/ecu_controller.h"
#include <cassert>
#include <cmath>
#include <initializer_list>
int main() {
  EcuController ecu;
  ecu.set_accelerator_adc(0, 4095);
  ecu.update_control(0);
  assert(ecu.accelerator == 0 && ecu.injection_us == 0);
  ecu.set_accelerator_adc(4095, 4095);
  ecu.update_control(10000);
  assert(ecu.accelerator == 1 && ecu.injection_us == ECU_INJECTION_US);
  for (unsigned maximum : {1023u, 4095u}) {
    unsigned raw =
        (unsigned)lround((ECU_PEDAL_MIN_V + ECU_PEDAL_MAX_V) / 2 / ECU_ADC_REFERENCE_V * maximum);
    ecu.set_accelerator_adc(raw, maximum);
    ecu.update_control(20000);
    assert(fabs(ecu.accelerator - .5) < .002);
    assert(fabs((double)ecu.injection_us - ECU_INJECTION_US / 2.0) < 6);
  }
  ecu.set_accelerator(-1);
  assert(ecu.accelerator == 0);
  ecu.set_accelerator(2);
  assert(ecu.accelerator == 1);
  return 0;
}
