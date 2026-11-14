#!/usr/bin/env python3
"""Vytvoří statický integrační podnět pro Wokwi (není testem fyzikální uzavřené smyčky)."""
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT.parents[1]))
from engine import Engine
from protocol import message,encode

def main():
    steps=[]
    for i in range(41):
        time=i*50000
        state=Engine().snapshot()
        state.update(rpm=1000,cycle_angle_deg=(time*.006)%720,crank_angle_deg=(time*.006)%360)
        if i >= 20:
            state.update(map_kpa=100,tps=.8,throttle=.8,iat_c=40,clt_c=60,lambda_value=1.02)
        state['hardware']={'session':1234,'mode':'buffered','lookahead_us':100000}
        frame=encode(message('engine_state',i+1,time,state),integrity=True).decode()
        # JSON string je platný YAML quoted scalar; \n zůstane skutečným LF při načtení YAML.
        steps.append('  - write-serial: '+json.dumps(frame))
        steps.append('  - delay: 50ms')
    steps.extend(['  - wait-serial: \'"action":"spark"\'', '  - delay: 1500ms',
                  '  - expect-pin:', '      part-id: engine', '      name: CKP', '      value: 0',
                  '  - expect-pin:', '      part-id: engine', '      name: CMP', '      value: 0'])
    path=ROOT/'tests/prototype.yaml'
    path.write_text("name: 'ECU hardware topology prototype – constant 1000 RPM'\nversion: 1\nauthor: 'ECU Simulator'\nsteps:\n"+'\n'.join(steps)+'\n')
    print(path)
if __name__=='__main__':main()
