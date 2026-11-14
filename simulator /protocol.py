"""Verzovaný JSON Lines protokol a omezený dekodér rámců."""
import json
import math

MAX_FRAME = 16384

def validate(obj):
    if not isinstance(obj,dict):
        raise ValueError('message must be an object')
    required = {'version','type','sequence','simulation_time_us','source','data','error'}
    if not required <= obj.keys() or type(obj['version']) is not int or obj['version'] != 1:
        raise ValueError('invalid protocol envelope/version')
    for key in ('sequence','simulation_time_us'):
        if type(obj[key]) is not int or obj[key] < 0:
            raise ValueError('invalid '+key)
    if obj['type'] not in ('engine_state','actuators','ecu_event','signal_events','clock_sync','error'):
        raise ValueError('unknown message type')
    if not isinstance(obj['source'],str) or not obj['source'] or not isinstance(obj['data'],dict):
        raise ValueError('invalid source/data')
    if obj['error'] is not None and not isinstance(obj['error'],dict):
        raise ValueError('invalid error')
    def finite(value):
        if isinstance(value,float) and not math.isfinite(value):
            raise ValueError('non-finite number')
        if isinstance(value,dict):
            for v in value.values(): finite(v)
        if isinstance(value,list):
            for v in value: finite(v)
    finite(obj)
    return obj

def message(kind, sequence, time_us, data, source='host', error=None):
    return validate(dict(version=1,type=kind,sequence=sequence,simulation_time_us=time_us,
                         source=source,data=data,error=error))

def encode(obj):
    raw = (json.dumps(validate(obj), separators=(',',':'),allow_nan=False)+'\n').encode()
    if len(raw) > MAX_FRAME:
        raise ValueError('frame too large')
    return raw

def decode(raw):
    if len(raw) > MAX_FRAME:
        raise ValueError('frame too large')
    try:
        return validate(json.loads(raw))
    except (UnicodeDecodeError, RecursionError) as exc:
        raise ValueError('invalid JSON') from exc

class LineDecoder:
    def __init__(self):
        self.buffer = bytearray()
        self.discarding = False
        self.errors = 0

    def feed(self, chunk):
        result = []
        for byte in chunk:
            if byte == 10:
                if not self.discarding and self.buffer:
                    try: result.append(decode(self.buffer))
                    except (ValueError, RecursionError): self.errors += 1
                self.buffer.clear()
                self.discarding = False
            elif not self.discarding:
                self.buffer.append(byte)
                if len(self.buffer) >= MAX_FRAME:
                    self.buffer.clear()
                    self.discarding = True
                    self.errors += 1
        return result
