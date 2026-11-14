#!/usr/bin/env python3
"""Hostitel se společnou geometrií, počtem válců a komunikačními parametry."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
ROOT=Path(__file__).resolve().parents[1]

def host_configuration(hardware):
    config=json.loads((ROOT.parents[1]/'engine_config.json').read_text())
    config['engine']['cylinders']=hardware['cylinders']
    config['signals']={'teeth':hardware['ckp']['teeth'],'missing':hardware['ckp']['missing'],
                       'cmp_positions':hardware['cmp']['positions_deg'],'cmp_width':hardware['cmp']['width_deg']}
    return config

if __name__=='__main__':
    hardware=json.loads((ROOT/'config/engine.json').read_text());comm=hardware['communication']
    with tempfile.TemporaryDirectory(prefix='ecu-hardware-host-') as directory:
        config_path=Path(directory)/'engine.json'
        config_path.write_text(json.dumps(host_configuration(hardware)))
        command=[sys.executable,str(ROOT.parents[1]/'main.py'),'--mode','wokwi','--wokwi-hardware',
                 '--config',str(config_path),'--url',f"rfc2217://{comm['host']}:{comm['rfc2217_port']}",
                 '--baudrate',str(comm['baudrate']),'--hardware-mode',comm['mode'],
                 '--lookahead-us',str(comm['lookahead_us']),*sys.argv[1:]]
        raise SystemExit(subprocess.call(command))
