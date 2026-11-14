// Lokální čas Wokwi. Není zde socket ani předpokládané síťové API.
#include "wokwi-api.h"
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef struct {
  pin_t ckp,cmp,analog[5],injector[4],coil[4];
  uart_dev_t uart;
  double angle,rpm;
  uint64_t last;
  char input[96];
  unsigned used;
  uint32_t queue[64][4],head,tail,dropped;
  uint8_t tx[96];
  bool busy;
  bool discard;
} chip_state_t;

static double bounded(double v,double low,double high) {return fmax(low,fmin(high,v));}
static void on_rx(void *user,uint8_t byte) {
  chip_state_t *s=user;
  if(byte=='\n') {
    s->input[s->used]=0;
    long rpm,map,tps,iat,clt,lambda;
    if(!s->discard && sscanf(s->input,"S %ld %ld %ld %ld %ld %ld",&rpm,&map,&tps,&iat,&clt,&lambda)==6) {
      s->rpm=bounded(rpm/100.0,0,7500);
      // Výukové lineární převody, nikoli charakteristiky skutečných snímačů.
      double volts[5]={map/4000.0,tps/20.0,(iat/100.0+40)/33,
                       (clt/100.0+40)/33,(lambda/100.0-.5)/.3};
      for(int i=0;i<5;i++) pin_dac_write(s->analog[i],bounded(volts[i],0,5));
    }
    s->used=0;s->discard=false;
  } else if(!s->discard) {
    if(s->used<sizeof(s->input)-1) s->input[s->used++]=byte;
    else {s->used=0;s->discard=true;}
  }
}
static void tx_done(void *user) { ((chip_state_t *)user)->busy=false; }
static void tick(void *user) {
  chip_state_t *s=user;
  uint64_t now=get_sim_nanos();
  if(!s->busy && s->tail!=s->head) {
    uint32_t *e=s->queue[s->tail];
    int n=snprintf((char *)s->tx,sizeof(s->tx),"E %lu %lu %lu %lu\n",
                   (unsigned long)e[0],(unsigned long)e[1],(unsigned long)e[2],(unsigned long)e[3]);
    if(uart_write(s->uart,s->tx,n)) {s->busy=true;s->tail=(s->tail+1)%64;}
  }
  s->angle=fmod(s->angle+s->rpm*6*(now-s->last)/1e9,720);
  s->last=now;
  // Tolerance pouze pro numerické zaokrouhlení přesné hranice cyklu.
  double cycle=fmod(s->angle+1e-8,720);
  double tooth=fmod(cycle,360)/6;
  pin_write(s->ckp,((int)tooth<58 && tooth-floor(tooth)<.5)?HIGH:LOW);
  pin_write(s->cmp,cycle<12?HIGH:LOW);
}
static void capture(void *user,pin_t pin,uint32_t level) {
  chip_state_t *s=user;
  for(int i=0;i<4;i++) {
    if(pin==s->injector[i] || pin==s->coil[i]) {
      unsigned next=(s->head+1)%64;
      if(next==s->tail) {s->dropped++;printf("CAPTURE_OVERFLOW %u\n",s->dropped);return;}
      uint32_t *e=s->queue[s->head];
      e[0]=(uint32_t)(get_sim_nanos()/1000);e[1]=pin==s->coil[i];e[2]=i;e[3]=level;
      s->head=next;
      // Záznam v doméně ECU, nezávislý na příchodu TCP rámce.
      printf("ECU_EDGE %llu %s %d %u\n",(unsigned long long)(get_sim_nanos()/1000),
             pin==s->injector[i]?"injector":"coil",i,(unsigned)level);
    }
  }
}
void chip_init(void) {
  chip_state_t *s=calloc(1,sizeof(*s));
  s->last=get_sim_nanos();
  s->ckp=pin_init("CKP",OUTPUT_HIGH);s->cmp=pin_init("CMP",OUTPUT_HIGH);
  const char *names[]={"MAP","TPS","IAT","CLT","LAMBDA"};
  for(int i=0;i<5;i++) {s->analog[i]=pin_init(names[i],ANALOG);pin_dac_write(s->analog[i],0);}
  for(int i=0;i<4;i++) {
    char name[8];snprintf(name,sizeof(name),"INJ%d",i);s->injector[i]=pin_init(name,INPUT);
    snprintf(name,sizeof(name),"COIL%d",i);s->coil[i]=pin_init(name,INPUT);
    const pin_watch_config_t watch={.edge=BOTH,.pin_change=capture,.user_data=s};
    pin_watch(s->injector[i],&watch);pin_watch(s->coil[i],&watch);
  }
  const uart_config_t uart={.rx=pin_init("RX",INPUT),.tx=pin_init("TX",INPUT_PULLUP),
                          .baud_rate=1000000,.rx_data=on_rx,.write_done=tx_done,.user_data=s};
  s->uart=uart_init(&uart);
  const timer_config_t timer={.callback=tick,.user_data=s};
  timer_t id=timer_init(&timer);timer_start(id,10,true);
}
