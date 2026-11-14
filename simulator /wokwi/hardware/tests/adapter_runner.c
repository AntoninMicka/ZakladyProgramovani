// Nativní prototyp téhož adaptéru: JSON vstup/výstup, čas posouvá test, ne OS.
#include <stdio.h>
#include <string.h>
#include "../chips/engine-interface/adapter.h"
#include "../config/generated_hw.h"
static hw_core_t core;static adapter_t adapter;
static void digital(void *u,unsigned s,unsigned v) {(void)u;(void)s;(void)v;}
static void analog(void *u,unsigned i,double v) {(void)u;(void)i;(void)v;}
static void event(void *u,const hw_event_t *e) {(void)u;adapter_event(&adapter,e);}
int main(void) {
  hw_init(&core,&HW_CONFIG,(hw_hooks_t){NULL,digital,analog,event},0);adapter_init(&adapter,&core);
  char line[32768];
  while(fgets(line,sizeof(line),stdin)) {
    unsigned kind,channel,level;unsigned long long time;
    if(sscanf(line,"TIME %llu",&time)==1) {
      while(hw_deadline(&core)<=time)hw_run(&core,hw_deadline(&core));hw_run(&core,time);
    } else if(sscanf(line,"PIN %u %u %u",&kind,&channel,&level)==3)hw_capture(&core,kind,channel,level,core.now_us);
    else if(!strcmp(line,"STATUS\n"))adapter_status(&adapter,core.now_us);
    else for(size_t i=0;i<strlen(line);i++)adapter_feed(&adapter,(uint8_t)line[i],core.now_us);
    const char *out;while((out=adapter_output(&adapter))) {fputs(out,stdout);adapter_output_done(&adapter);}
  }
  return 0;
}
