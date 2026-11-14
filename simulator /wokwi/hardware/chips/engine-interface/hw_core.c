#include "hw_core.h"
#include <math.h>
#include <string.h>

static double wrap(double x,double period) { double a=fmod(x,period);return a<0?a+period:a; }
static unsigned signal_level(const hw_core_t *s,unsigned signal) {
  double angle=wrap(s->angle+1e-8,720),phase;
  bool active=false;
  if(!signal) {
    phase=wrap(angle,360)/(360.0/s->cfg->teeth);
    int tooth=(int)floor(phase);
    active=tooth<(int)(s->cfg->teeth-s->cfg->missing) && tooth!=s->cfg->skip_tooth && phase-tooth<s->cfg->duty;
    if(s->cfg->noise_angle>=0 && wrap(angle-s->cfg->noise_angle,360)<s->cfg->noise_width)active=true;
    return active?s->cfg->ckp_high:!s->cfg->ckp_high;
  }
  if(!s->cfg->cmp_stuck)for(unsigned i=0;i<s->cfg->cmp_count;i++)
    if(wrap(angle-s->cfg->cmp_positions[i]-s->cfg->cmp_offset,720)<s->cfg->cmp_width)active=true;
  return active?s->cfg->cmp_high:!s->cfg->cmp_high;
}
static void outputs(hw_core_t *s,bool stopped) {
  for(unsigned i=0;i<2;i++) {
    unsigned value=stopped?(i?!s->cfg->cmp_high:!s->cfg->ckp_high):signal_level(s,i);
    if(s->level[i]!=value) {s->level[i]=value;s->hooks.digital(s->hooks.user,i,value);}
  }
}
static uint64_t simulation_time(const hw_core_t *s,uint64_t local) {
  if(!s->mapped || local<s->origin_local_us)return 0;
  return s->origin_sim_us+local-s->origin_local_us;
}
static void emit(hw_core_t *s,unsigned kind,unsigned channel,unsigned action,unsigned error,uint64_t now,uint64_t duration) {
  hw_event_t event={.time_us=now,.simulation_us=simulation_time(s,now),.duration_us=duration,
                    .kind=kind,.channel=channel,.action=action,.error=error,.angle=wrap(s->angle,720)};
  if(!s->mapped && !error)event.error=5;
  s->hooks.event(s->hooks.user,&event);
}
static void abort_pulses(hw_core_t *s,uint64_t now,unsigned error) {
  for(unsigned kind=0;kind<2;kind++)for(unsigned i=0;i<HW_CHANNELS;i++)if(s->active[kind][i]) {
    emit(s,kind,i,2,error,now,now-s->starts[kind][i]);s->active[kind][i]=false;
  }
}
void hw_init(hw_core_t *s,const hw_config_t *cfg,hw_hooks_t hooks,uint64_t now) {
  memset(s,0,sizeof(*s));s->cfg=cfg;s->hooks=hooks;s->now_us=now;
  s->level[0]=s->level[1]=2;outputs(s,true);
}
void hw_reset(hw_core_t *s,uint64_t now) {
  hw_run(s,now);abort_pulses(s,now,3);
  s->queued=0;s->running=false;s->mapped=false;s->rpm=0;s->angle=0;
  outputs(s,true);
}
double hw_voltage(const hw_curve_t *c,double value) {
  if(value<=c->x[0])return c->v[0];
  for(unsigned i=1;i<c->count;i++)if(value<=c->x[i]) {
    double f=(value-c->x[i-1])/(c->x[i]-c->x[i-1]);return c->v[i-1]+f*(c->v[i]-c->v[i-1]);
  }
  return c->v[c->count-1];
}
static void advance(hw_core_t *s,uint64_t until) {
  if(s->running)s->angle=wrap(s->angle+s->rpm*6*(until-s->now_us)/1e6,720);
  s->now_us=until;
}
static void apply(hw_core_t *s,const hw_state_t *state) {
  if(!s->mapped) {
    s->origin_local_us=state->apply_us;s->origin_sim_us=state->simulation_us;
    s->angle=state->cycle_angle;s->mapped=true;
  }
  s->phase_error=wrap(state->cycle_angle-s->angle+360,720)-360;
  s->rpm=state->rpm;s->running=true;s->last_apply_us=state->apply_us;
  for(unsigned i=0;i<5;i++)s->hooks.analog(s->hooks.user,i,hw_voltage(&s->cfg->analog[i],state->sensors[i]));
}
void hw_run(hw_core_t *s,uint64_t now) {
  if(now<s->now_us)return;
  while(s->queued && s->queue[0].apply_us<=now) {
    hw_state_t state=s->queue[0];
    advance(s,state.apply_us);apply(s,&state);
    memmove(s->queue,s->queue+1,(--s->queued)*sizeof(hw_state_t));
  }
  advance(s,now);
  if(s->running && now-s->last_apply_us>=s->cfg->watchdog_us) {
    s->running=false;s->rpm=0;s->timeouts++;if(s->buffered)s->underruns++;abort_pulses(s,now,3);
  }
  for(unsigned kind=0;kind<2;kind++)for(unsigned i=0;i<HW_CHANNELS;i++)if(s->active[kind][i] && now-s->starts[kind][i]>=s->cfg->max_pulse_us) {
    emit(s,kind,i,4,4,now,now-s->starts[kind][i]);s->active[kind][i]=false;s->invalid_pulses++;
  }
  outputs(s,!s->running || s->rpm==0);
}
bool hw_enqueue(hw_core_t *s,const hw_state_t *state,uint64_t now,bool buffered) {
  hw_run(s,now);
  if(state->apply_us<now) {s->late++;return false;}
  if(s->queued>=HW_QUEUE) {s->overflows++;return false;}
  if(s->queued && state->apply_us<=s->queue[s->queued-1].apply_us) {s->late++;return false;}
  s->queue[s->queued++]=*state;s->buffered=buffered;
  return true;
}
static void consider_angle(const hw_core_t *s,double target,double period,double *distance) {
  double delta=wrap(target-wrap(s->angle,period),period);
  if(delta<1e-7)delta=period;
  if(delta<*distance)*distance=delta;
}
uint64_t hw_deadline(const hw_core_t *s) {
  uint64_t next=s->queued?s->queue[0].apply_us:HW_NEVER;
  if(s->running) {
    uint64_t timeout=s->last_apply_us+s->cfg->watchdog_us;
    if(timeout<next)next=timeout;
    if(s->rpm>0) {
      double delta=720;
      for(unsigned i=0;i<s->cfg->teeth-s->cfg->missing;i++)if((int)i!=s->cfg->skip_tooth) {
        consider_angle(s,i*360.0/s->cfg->teeth,360,&delta);
        consider_angle(s,(i+s->cfg->duty)*360.0/s->cfg->teeth,360,&delta);
      }
      if(s->cfg->noise_angle>=0) {
        consider_angle(s,s->cfg->noise_angle,360,&delta);
        consider_angle(s,s->cfg->noise_angle+s->cfg->noise_width,360,&delta);
      }
      if(!s->cfg->cmp_stuck)for(unsigned i=0;i<s->cfg->cmp_count;i++) {
        consider_angle(s,s->cfg->cmp_positions[i]+s->cfg->cmp_offset,720,&delta);
        consider_angle(s,s->cfg->cmp_positions[i]+s->cfg->cmp_offset+s->cfg->cmp_width,720,&delta);
      }
      uint64_t edge=s->now_us+(uint64_t)fmax(1,ceil(delta*1e6/(s->rpm*6)-1e-7));
      if(edge<next)next=edge;
    }
  }
  for(unsigned k=0;k<2;k++)for(unsigned ch=0;ch<HW_CHANNELS;ch++)if(s->active[k][ch]) {
    uint64_t timeout=s->starts[k][ch]+s->cfg->max_pulse_us;if(timeout<next)next=timeout;
  }
  return next;
}
void hw_capture(hw_core_t *s,unsigned kind,unsigned channel,unsigned value,uint64_t now) {
  hw_run(s,now);
  if(kind>1 || channel>=(kind?s->cfg->ignitions:s->cfg->injectors))return;
  bool active=value==(kind?s->cfg->ignition_high:s->cfg->injector_high);
  if(active) {
    if(s->active[kind][channel]) {emit(s,kind,channel,3,1,now,0);s->invalid_pulses++;return;}
    s->active[kind][channel]=true;s->starts[kind][channel]=now;emit(s,kind,channel,0,0,now,0);
  } else {
    if(!s->active[kind][channel]) {emit(s,kind,channel,3,2,now,0);s->invalid_pulses++;return;}
    s->active[kind][channel]=false;emit(s,kind,channel,1,0,now,now-s->starts[kind][channel]);
  }
}
