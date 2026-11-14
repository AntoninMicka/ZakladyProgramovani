// Generated from config/*.json.
#pragma once
#define ECU_DIAG_BAUD 115200
#define ECU_CYLINDERS 4
#define ECU_CKP_PIN 27
#define ECU_CMP_PIN 26
#define ECU_TEETH 60
#define ECU_MISSING 2
#define ECU_CKP_ACTIVE 1
#define ECU_CMP_ACTIVE 1
#define ECU_CMP_REFERENCE 0
#define ECU_INJ_ACTIVE 1
#define ECU_IGN_ACTIVE 1
#define ECU_INJECTION_US 3000
#define ECU_DWELL_US 2000
#define ECU_ADVANCE_DEG 15
#define ECU_TIMER_US 25
#define ECU_ADC_REFERENCE_V 5.0
#define ECU_PEDAL_MIN_V 0.33
#define ECU_PEDAL_MAX_V 2.97
static const unsigned INJECTOR_PINS[]={16,17,18,19};
static const unsigned IGNITION_PINS[]={21,22,23,25};
static const unsigned ANALOG_PINS[]={32,33,34,35,36};
static const unsigned FIRING_ORDER[]={1,3,4,2};
