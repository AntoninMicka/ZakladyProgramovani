#include "json.h"
#include <ctype.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static void whitespace(const json_doc_t *d,int *p) {while(*p<d->length && strchr(" \r\n\t",d->text[*p]))(*p)++;}
static int value(json_doc_t *d,int *p,int parent,unsigned depth) {
  if(depth>16 || d->count>=JSON_TOKENS)return -1;
  whitespace(d,p);if(*p>=d->length)return -1;
  int index=d->count++,start=*p;char type=d->text[*p];
  d->token[index]=(json_token_t){.start=start,.parent=parent,.type=type};
  if(type=='{' || type=='[') {
    (*p)++;whitespace(d,p);char end=type=='{'?'}':']';
    if(*p<d->length && d->text[*p]==end)(*p)++;
    else while(1) {
      if(type=='{') {
        whitespace(d,p);if(*p>=d->length || d->text[*p]!='"')return -1;
        if(value(d,p,index,depth+1)<0)return -1;
        whitespace(d,p);if(*p>=d->length || d->text[(*p)++]!=':')return -1;
      }
      if(value(d,p,index,depth+1)<0)return -1;
      whitespace(d,p);if(*p>=d->length)return -1;
      char c=d->text[(*p)++];if(c==end)break;if(c!=',')return -1;
    }
  } else if(type=='"') {
    (*p)++;bool closed=false;
    while(*p<d->length) {
      unsigned char c=d->text[(*p)++];
      if(c=='"') {closed=true;break;}
      if(c<32)return -1;
      if(c=='\\') {
        if(*p>=d->length)return -1;char e=d->text[(*p)++];
        if(e=='u') {for(int i=0;i<4;i++)if(*p>=d->length || !isxdigit((unsigned char)d->text[(*p)++]))return -1;}
        else if(!strchr("\"\\/bfnrt",e))return -1;
      }
    }
    if(!closed)return -1;
  } else {
    while(*p<d->length && !strchr(" \r\n\t,]}",d->text[*p]))(*p)++;
    int length=*p-start;
    if(length<=0 || length>=64)return -1;
    char raw[64];memcpy(raw,d->text+start,length);raw[length]=0;
    if(strcmp(raw,"true") && strcmp(raw,"false") && strcmp(raw,"null")) {
      int q=0;if(raw[q]=='-')q++;
      if(raw[q]=='0')q++;else {if(raw[q]<'1'||raw[q]>'9')return -1;while(isdigit((unsigned char)raw[q]))q++;}
      if(raw[q]=='.') {q++;if(!isdigit((unsigned char)raw[q]))return -1;while(isdigit((unsigned char)raw[q]))q++;}
      if(raw[q]=='e'||raw[q]=='E') {q++;if(raw[q]=='+'||raw[q]=='-')q++;if(!isdigit((unsigned char)raw[q]))return -1;while(isdigit((unsigned char)raw[q]))q++;}
      if(raw[q])return -1;
      char *end;double n=strtod(raw,&end);if(*end || !isfinite(n))return -1;
    }
  }
  d->token[index].end=*p;return index;
}
bool json_parse(json_doc_t *d,const char *text,size_t length) {
  if(length>16383)return false;
  *d=(json_doc_t){.text=text,.length=(int)length};int p=0;
  if(value(d,&p,-1,0)!=0)return false;
  whitespace(d,&p);return p==d->length && d->token[0].type=='{';
}
bool json_equal(const json_doc_t *d,int index,const char *text) {
  if(index<0)return false;
  json_token_t t=d->token[index];
  if(t.type=='"') {t.start++;t.end--;}
  return (size_t)(t.end-t.start)==strlen(text) && !memcmp(d->text+t.start,text,strlen(text));
}
int json_get(const json_doc_t *d,int parent,const char *key) {
  if(parent<0)return -1;
  int found=-1;
  for(int i=parent+1;i<d->count;i++)if(d->token[i].parent==parent) {
    int name=i;int val=i+1;if(val>=d->count || d->token[val].parent!=parent)return -1;
    if(json_equal(d,name,key)) {if(found>=0)return -1;found=val;}
    i=val;
    while(i+1<d->count && d->token[i+1].start<d->token[val].end)i++;
  }
  return found;
}
bool json_number(const json_doc_t *d,int index,double *out) {
  if(index<0)return false;
  json_token_t t=d->token[index];if(t.type!='-' && !isdigit((unsigned char)t.type))return false;
  char raw[64];int n=t.end-t.start;if(n>=64)return false;
  memcpy(raw,d->text+t.start,n);raw[n]=0;char *end;*out=strtod(raw,&end);
  return !*end && isfinite(*out);
}
uint32_t json_crc32(const char *bytes,size_t length) {
  uint32_t crc=~0u;
  for(size_t i=0;i<length;i++) {crc^=(unsigned char)bytes[i];for(int j=0;j<8;j++)crc=(crc>>1)^((0u-(crc&1))&0xedb88320u);}
  return ~crc;
}
bool json_integrity(const json_doc_t *d) {
  int integrity=json_get(d,0,"integrity"),crc=json_get(d,integrity,"crc32");
  if(integrity<1 || crc<0 || d->token[crc].type!='"' || d->token[crc].end-d->token[crc].start!=10)return false;
  if(d->token[integrity].end!=d->token[0].end-1)return false;
  int comma=d->token[integrity-1].start-1;
  if(comma<0 || d->text[comma]!=',')return false;
  char base[16384];memcpy(base,d->text,comma);base[comma]='}';
  char hex[9];memcpy(hex,d->text+d->token[crc].start+1,8);hex[8]=0;
  for(int i=0;i<8;i++)if(!isxdigit((unsigned char)hex[i]))return false;
  return json_crc32(base,comma+1)==(uint32_t)strtoul(hex,NULL,16);
}
size_t json_protect(char *buffer,size_t capacity) {
  size_t n=strlen(buffer);if(!n || buffer[n-1]!='}' || n+40>=capacity)return 0;
  uint32_t crc=json_crc32(buffer,n);
  int added=snprintf(buffer+n-1,capacity-n+1,",\"integrity\":{\"crc32\":\"%08lx\"}}\n",(unsigned long)crc);
  return added>0?n-1+(size_t)added:0;
}
