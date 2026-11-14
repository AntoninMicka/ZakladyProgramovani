#pragma once
// Pouze dekódování snímačů a řízení výstupů. Žádná dynamika motoru ani simulační protokol.
#include <stdint.h>
#include <math.h>
#include "generated_pins.h"
struct EcuController {
  uint32_t last_ckp=0,normal_us=0,cam_time=0,edges=0,cam_edges=0,errors=0;
  uint32_t injector_end[4]={},coil_end[4]={};
  bool injector_on[4]={},coil_on[4]={};
  bool have_ckp=false,gap_seen=false,synced=false,have_phase=false;
  unsigned slot=0,revolution=0;
  double rpm=0,phase_at_edge=0,last_phase=0;
  static double wrap(double angle) {double r=fmod(angle,720);return r<0?r+720:r;}
  void cam(uint32_t now) {
    cam_time=now;cam_edges++;
    if(!have_ckp || !normal_us || !gap_seen)return;
    double angle=slot*(360.0/ECU_TEETH)+(now-last_ckp)*6*rpm/1e6;
    double delta=fmod(angle-ECU_CMP_REFERENCE+540,360)-180;
    if(fabs(delta)<2*360.0/ECU_TEETH) {
      revolution=ECU_CMP_REFERENCE>=360;phase_at_edge=revolution*360+slot*(360.0/ECU_TEETH);
      synced=true;
    } else {synced=false;errors++;}
  }
  void crank(uint32_t now) {
    edges++;
    if(!have_ckp) {have_ckp=true;last_ckp=now;return;}
    uint32_t interval=now-last_ckp;
    if(!interval)return;
    if(normal_us && interval<normal_us*.45) {errors++;return;}
    bool gap=normal_us && interval>normal_us*1.8;
    if(gap) {
      double expected=(ECU_MISSING+1)*normal_us;
      if(fabs(interval-expected)>expected*.35) {errors++;synced=false;}
      revolution^=1;slot=0;gap_seen=true;
    } else {
      normal_us=normal_us?(normal_us*3+interval)/4:interval;
      slot++;
      if(slot>=ECU_TEETH-ECU_MISSING) {slot%=ECU_TEETH;errors++;synced=false;}
    }
    last_ckp=now;
    rpm=normal_us?60000000.0/(ECU_TEETH*normal_us):0;
    phase_at_edge=revolution*360+slot*(360.0/ECU_TEETH);
  }
  template<class Write> void stop(Write write) {
    for(unsigned i=0;i<ECU_CYLINDERS;i++) {
      if(injector_on[i])write(false,i,!ECU_INJ_ACTIVE);
      if(coil_on[i])write(true,i,!ECU_IGN_ACTIVE);
      injector_on[i]=coil_on[i]=false;
    }
    synced=false;have_phase=false;rpm=0;have_ckp=false;normal_us=0;gap_seen=false;slot=0;
  }
  static bool crossed(double before,double after,double target) {
    double distance=wrap(target-before),travel=wrap(after-before);
    return distance>1e-7 && distance<=travel+1e-7 && travel<180;
  }
  template<class Write> void tick(uint32_t now,Write write) {
    if(have_ckp && normal_us && now-last_ckp>normal_us*5+1000) {stop(write);return;}
    for(unsigned i=0;i<ECU_CYLINDERS;i++) {
      if(injector_on[i] && (int32_t)(now-injector_end[i])>=0) {write(false,i,!ECU_INJ_ACTIVE);injector_on[i]=false;}
      if(coil_on[i] && (int32_t)(now-coil_end[i])>=0) {write(true,i,!ECU_IGN_ACTIVE);coil_on[i]=false;}
    }
    if(!synced || rpm<=0) {have_phase=false;return;}
    double phase=wrap(phase_at_edge+(now-last_ckp)*6*rpm/1e6);
    if(have_phase)for(unsigned order=0;order<ECU_CYLINDERS;order++) {
      unsigned channel=FIRING_ORDER[order]-1;
      double fire=order*720.0/ECU_CYLINDERS;
      if(!injector_on[channel] && crossed(last_phase,phase,wrap(fire+360))) {
        write(false,channel,ECU_INJ_ACTIVE);injector_on[channel]=true;injector_end[channel]=now+ECU_INJECTION_US;
      }
      double charge=wrap(fire-ECU_ADVANCE_DEG-ECU_DWELL_US*6*rpm/1e6);
      if(!coil_on[channel] && crossed(last_phase,phase,charge)) {
        write(true,channel,ECU_IGN_ACTIVE);coil_on[channel]=true;coil_end[channel]=now+ECU_DWELL_US;
      }
    }
    last_phase=phase;have_phase=true;
  }
};
