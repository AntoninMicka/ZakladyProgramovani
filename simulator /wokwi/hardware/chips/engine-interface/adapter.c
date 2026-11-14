#include "adapter.h"
#include <math.h>
#include <stdio.h>
#include <string.h>

static char *begin(adapter_t *a) {
  unsigned next=(a->head+1)%ADAPTER_TX_QUEUE;
  if(next==a->tail) {a->dropped++;return NULL;}
  return a->output[a->head];
}
static void commit(adapter_t *a) {
  if(json_protect(a->output[a->head],ADAPTER_TX_FRAME))a->head=(a->head+1)%ADAPTER_TX_QUEUE;
  else a->dropped++;
}
void adapter_init(adapter_t *a,hw_core_t *core) {memset(a,0,sizeof(*a));a->core=core;}
const char *adapter_output(adapter_t *a) {return a->head==a->tail?NULL:a->output[a->tail];}
void adapter_output_done(adapter_t *a) {if(a->head!=a->tail)a->tail=(a->tail+1)%ADAPTER_TX_QUEUE;}
static bool num(json_doc_t *d,int parent,const char *key,double lo,double hi,double *v) {
  return json_number(d,json_get(d,parent,key),v) && *v>=lo && *v<=hi;
}
static bool whole(json_doc_t *d,int parent,const char *key,double hi,uint64_t *out) {
  int index=json_get(d,parent,key);
  if(index<0)return false;
  for(int i=d->token[index].start;i<d->token[index].end;i++)if(d->text[i]<'0'||d->text[i]>'9')return false;
  double v;if(!num(d,parent,key,0,hi,&v) || floor(v)!=v)return false;*out=(uint64_t)v;return true;
}
static void echo(adapter_t *a,uint64_t sequence,uint64_t simulation,uint64_t now) {
  char *out=begin(a);if(!out)return;
  snprintf(out,ADAPTER_TX_FRAME,"{\"version\":1,\"type\":\"clock_sync\",\"source\":\"engine-interface\",\"sequence\":%llu,\"simulation_time_us\":%llu,\"data\":{\"echo_sequence\":%llu,\"ecu_time_us\":%llu,\"hardware_session\":%lu},\"error\":null}",
           (unsigned long long)++a->sequence,(unsigned long long)simulation,(unsigned long long)sequence,
           (unsigned long long)now,(unsigned long)a->session);commit(a);
}
static bool receive(adapter_t *a,uint64_t now) {
  json_doc_t *d=&a->doc;
  if(!json_parse(d,a->input,a->used))return false;
  if(!json_integrity(d)) {a->crc_errors++;return false;}
  uint64_t version,sequence,simulation,session;
  if(!whole(d,0,"version",1,&version) || version!=1 || !whole(d,0,"sequence",9007199254740991.0,&sequence) ||
     !whole(d,0,"simulation_time_us",9007199254740991.0,&simulation))return false;
  int data=json_get(d,0,"data"),source=json_get(d,0,"source"),error=json_get(d,0,"error");
  if(data<0 || d->token[data].type!='{' || source<0 || !json_equal(d,source,"host") ||
     error<0 || d->token[error].type!='n' || !json_equal(d,error,"null"))return false;
  int hardware=json_get(d,data,"hardware");
  if(hardware<0 || !whole(d,hardware,"session",4294967295.0,&session))return false;
  bool reset=json_equal(d,json_get(d,0,"type"),"hardware_reset");
  if(!reset && !json_equal(d,json_get(d,0,"type"),"engine_state"))return false;
  hw_state_t state={.simulation_us=simulation};
  if(!reset) {
    if(!num(d,data,"rpm",0,20000,&state.rpm) || !num(d,data,"cycle_angle_deg",0,719.999999999,&state.cycle_angle) ||
       !num(d,data,"map_kpa",0,300,&state.sensors[0]) || !num(d,data,"iat_c",-100,250,&state.sensors[2]) ||
       !num(d,data,"clt_c",-100,250,&state.sensors[3]))return false;
    if(!num(d,data,"tps",0,1,&state.sensors[1])) {
      if(!num(d,data,"tps_percent",0,100,&state.sensors[1]))return false;
      state.sensors[1]/=100;
    }
    if(!num(d,data,"lambda_value",.1,5,&state.sensors[4]) && !num(d,data,"lambda",.1,5,&state.sensors[4]))return false;
  }
  uint64_t lookahead;
  if(!whole(d,hardware,"lookahead_us",1000000,&lookahead) || lookahead<1000)return false;
  bool buffered=json_equal(d,json_get(d,hardware,"mode"),"buffered");
  if(!buffered && !json_equal(d,json_get(d,hardware,"mode"),"free"))return false;
  if(!a->session_set || session!=a->session || reset) {
    // Nejdříve uzavřeme pulzy staré epochy; jejich značky i session zůstanou staré.
    hw_reset(a->core,now);a->session=(uint32_t)session;a->session_set=true;a->resets++;
    a->have_sequence=false;a->origin_host=simulation;a->origin_local=now+lookahead;a->last_host=simulation;
  }
  if(a->have_sequence && (sequence<=a->last_sequence || (!reset && simulation<=a->last_host))) {a->stale++;return false;}
  if(simulation<a->origin_host || (buffered && a->origin_local+simulation-a->origin_host>now+2000000))return false;
  if(!reset) {
    state.apply_us=buffered?a->origin_local+simulation-a->origin_host:now;
    if(!hw_enqueue(a->core,&state,now,buffered))return false;
  }
  a->last_sequence=sequence;a->last_host=simulation;a->have_sequence=true;a->received++;
  echo(a,sequence,simulation,now);return true;
}
void adapter_feed(adapter_t *a,uint8_t byte,uint64_t now) {
  if(byte=='\n') {
    if(!a->discard && a->used) {a->input[a->used]=0;if(!receive(a,now))a->invalid++;}
    a->used=0;a->discard=false;
  } else if(!a->discard) {
    if(a->used<ADAPTER_FRAME-1)a->input[a->used++]=(char)byte;
    else {a->used=0;a->discard=true;a->invalid++;}
  }
}
void adapter_event(adapter_t *a,const hw_event_t *e) {
  char *out=begin(a);if(!out)return;
  const char *signal=e->kind?"ignition":"injector";
  const char *actions[2][5]={{"start","end","aborted","invalid","timeout"},{"charge","spark","aborted","invalid","timeout"}};
  char error[128]="null";
  if(e->error)snprintf(error,sizeof(error),"{\"code\":\"hardware_pulse_%u\",\"message\":\"Incomplete or invalid pulse\"}",e->error);
  snprintf(out,ADAPTER_TX_FRAME,"{\"version\":1,\"type\":\"ecu_event\",\"source\":\"engine-interface\",\"sequence\":%llu,\"simulation_time_us\":%llu,\"data\":{\"signal\":\"%s\",\"action\":\"%s\",\"channel\":%u,\"channel_name\":\"%s%u\",\"simulation_time_us\":%llu,\"ecu_time_us\":%llu,\"duration_us\":%llu,\"cycle_angle_deg\":%.6f,\"crank_angle_deg\":%.6f,\"hardware_session\":%lu},\"error\":%s}",
           (unsigned long long)++a->sequence,(unsigned long long)e->simulation_us,signal,actions[e->kind][e->action],e->channel,
           e->kind?"IGN":"INJ",e->channel+1,(unsigned long long)e->simulation_us,(unsigned long long)e->time_us,
           (unsigned long long)e->duration_us,e->angle,fmod(e->angle,360),(unsigned long)a->session,error);commit(a);
}
void adapter_status(adapter_t *a,uint64_t now) {
  hw_core_t *s=a->core;char *out=begin(a);if(!out)return;
  uint64_t sim=s->mapped && now>=s->origin_local_us?s->origin_sim_us+now-s->origin_local_us:0;
  snprintf(out,ADAPTER_TX_FRAME,"{\"version\":1,\"type\":\"hardware_status\",\"source\":\"engine-interface\",\"sequence\":%llu,\"simulation_time_us\":%llu,\"data\":{\"hardware_session\":%lu,\"wokwi_time_us\":%llu,\"running\":%s,\"queue_depth\":%u,\"phase_error_deg\":%.6f,\"received\":%lu,\"invalid\":%lu,\"crc_errors\":%lu,\"stale\":%lu,\"dropped_tx\":%lu,\"late_updates\":%lu,\"queue_overflows\":%lu,\"watchdog_timeouts\":%lu,\"invalid_pulses\":%lu,\"resets\":%lu},\"error\":null}",
    (unsigned long long)++a->sequence,(unsigned long long)sim,(unsigned long)a->session,(unsigned long long)now,
    s->running?"true":"false",s->queued,s->phase_error,(unsigned long)a->received,(unsigned long)a->invalid,
    (unsigned long)a->crc_errors,(unsigned long)a->stale,(unsigned long)a->dropped,(unsigned long)s->late,
    (unsigned long)s->overflows,(unsigned long)s->timeouts,(unsigned long)s->invalid_pulses,(unsigned long)a->resets);commit(a);
}
