"""Integrační kontrola skutečně exportovaného VCD; žádné tvrzení o neprovedeném běhu."""
import argparse
import re
from pathlib import Path
from statistics import median


def edges_from_vcd(path):
    text = Path(path).read_text()
    scale = re.search(r'\$timescale\s+(\d+)\s*(s|ms|us|ns|ps|fs)\s+\$end', text)
    if not scale:
        raise ValueError('VCD has no supported timescale')
    factor = int(scale[1])*{'s':1e6,'ms':1e3,'us':1,'ns':1e-3,'ps':1e-6,'fs':1e-9}[scale[2]]
    names = {code:name for code,name in re.findall(r'\$var\s+\S+\s+1\s+(\S+)\s+(\S+).*?\$end',text)}
    result = {name:[] for name in names.values()}
    previous, time_us = {}, 0
    body = text.split('$enddefinitions',1)[-1]
    for token in body.split():
        if token.startswith('#'):
            time_us = int(token[1:])*factor
        elif len(token)>1 and token[0] in '01' and token[1:] in names:
            code, level = token[1:],int(token[0])
            if code in previous and previous[code] != level:
                result[names[code]].append((time_us,level))
            previous[code] = level
    return result


def check(path,rpm,ckp='D0',cmp='D1',injector='D2',coil='D3',tolerance_us=30):
    if rpm<=0:
        raise ValueError('RPM must be positive and constant during capture')
    signals = edges_from_vcd(path)
    for name in (ckp,cmp,injector,coil):
        if name not in signals:
            raise ValueError('missing VCD signal '+name+'; available: '+', '.join(signals))
    rising = lambda name: [t for t,level in signals[name] if level]
    crank,cam = rising(ckp),rising(cmp)
    if len(crank)<120 or len(cam)<3:
        raise ValueError('capture at least three full revolutions/two CMP cycles')
    tooth_us = 60000000/(rpm*60)
    gaps = [b-a for a,b in zip(crank,crank[1:])]
    missing = []
    errors = []
    for i,gap in enumerate(gaps):
        expected = 3*tooth_us if gap>2*tooth_us else tooth_us
        if expected==3*tooth_us:missing.append(i)
        errors.append(abs(gap-expected))
    if len(missing)<2 or any(b-a!=58 for a,b in zip(missing,missing[1:])):
        raise ValueError('CKP is not a 60-2 pattern')
    if max(errors)>tolerance_us:
        raise ValueError('CKP timing error exceeds tolerance: '+str(max(errors)))
    cmp_errors = [abs((b-a)-120000000/rpm) for a,b in zip(cam,cam[1:])]
    if max(cmp_errors)>tolerance_us:
        raise ValueError('CMP period is not 720 degrees')
    for name,width in ((ckp,tooth_us/2),(cmp,120000000/rpm*12/720)):
        start = None
        for t,level in signals[name]:
            if level:start=t
            elif start is not None:
                if abs(t-start-width)>tolerance_us:
                    raise ValueError('pulse width mismatch: '+name)
                start=None
    pulses = {}
    for name in (injector,coil):
        widths,start = [],None
        for t,level in signals[name]:
            if level:start=t
            elif start is not None:
                widths.append(t-start);start=None
        if not widths or any(w<=0 for w in widths):
            raise ValueError('no complete output pulse: '+name)
        pulses[name] = {'count':len(widths),'median_width_us':median(widths)}
    return {'ckp_max_interval_error_us':max(errors),'cmp_max_period_error_us':max(cmp_errors),
            'missing_gaps':len(missing),'output_pulses':pulses}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('vcd',type=Path)
    parser.add_argument('--rpm',type=float,required=True)
    for name,default in [('ckp','D0'),('cmp','D1'),('injector','D2'),('coil','D3')]:
        parser.add_argument('--'+name,default=default)
    parser.add_argument('--tolerance-us',type=float,default=30)
    args = parser.parse_args()
    try:
        print(check(args.vcd,args.rpm,args.ckp,args.cmp,args.injector,args.coil,args.tolerance_us))
    except ValueError as exc:
        parser.exit(1,str(exc)+'\n')

if __name__=='__main__':main()
