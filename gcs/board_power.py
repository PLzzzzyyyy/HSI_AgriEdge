"""Chip model estimates, deliberately separate from measured power/energy fields."""
import json
import math
from pathlib import Path
import struct

MESSAGE=0x8c
PROFILE=json.loads(Path(__file__).with_name('chip_power_profile.json').read_text(encoding='utf-8'))

def watts(temperature):
    points=PROFILE['points']
    if temperature<=points[0]['temperature_c']:return points[0]['watts']
    for a,b in zip(points,points[1:]):
        if temperature<=b['temperature_c']:
            return a['watts']+(b['watts']-a['watts'])*(temperature-a['temperature_c'])/(b['temperature_c']-a['temperature_c'])
    return points[-1]['watts']

def decode(data,boot,session):
    if len(data)!=80 or struct.unpack_from('<HBB',data)!=(0x4548,MESSAGE,1):raise ValueError('Power estimate header')
    b,s,model,counter,age,task,flags,done,power,temp,energy,duration,fallback,total,pad=struct.unpack_from('<5IHHIffdQQII',data,12)
    if (b,s)!=(boot,session) or model!=int(PROFILE['model_id'],16) or not counter or pad or flags&~15 or not flags&1:
        raise ValueError('Power estimate identity/model')
    if bool(task)!=bool(flags&8) or bool(flags&4) and not task or done>total or fallback>duration:
        raise ValueError('Power estimate task')
    if struct.unpack_from('<H',data,4)[0]!=task or (not task and any((done,total,duration,fallback,energy))):raise ValueError('Power estimate task header')
    if not all(map(math.isfinite,(power,temp,energy))) or not -40<=temp<=125 or energy<0 or abs(power-watts(temp))>.0001:
        raise ValueError('Power estimate range')
    if not flags&2 and temp!=40:raise ValueError('Power reference temperature')
    if energy>max(p['watts'] for p in PROFILE['points'])*duration/1e6+.001:raise ValueError('Power estimate integral')
    return dict(measured=False,source=PROFILE['source'],scope=PROFILE['scope'],model_id=PROFILE['model_id'],
        confidence=PROFILE['points'][0]['confidence'],calibrated=False,boot_id=f'{b:08x}',session=s,task=task,
        counter=counter,sample_age_ms=age,power_est_w=power,temperature_used_c=temp,temperature_valid=bool(flags&2),
        energy_est_j=energy if task else None,duration_s=duration/1e6,fallback_s=fallback/1e6,
        active=bool(flags&4),done=done,total=total,
        energy_est_mj_per_px=1000*energy/done if done else None)

def accept_job(job,sample):
    """Identity-gated task display cache; journal packets remain the source."""
    a=job.audit
    if (sample['boot_id'],sample['session'],sample['task'])!=(f'{a.boot:08x}',a.session,a.task):return False
    if sample['total']!=a.total:raise ValueError('Power estimate ROI size')
    previous=getattr(job,'power_estimate',None)
    if previous:
        if sample['counter']<=previous['counter']:return False
        if sample['duration_s']<previous['duration_s'] or sample['energy_est_j']+1e-8<previous['energy_est_j']:
            raise ValueError('Power estimate regressed')
        if not previous['active'] and (sample['active'] or sample['duration_s']!=previous['duration_s'] or sample['energy_est_j']!=previous['energy_est_j']):
            raise ValueError('Finished power estimate changed')
    job.power_estimate=sample.copy();return True
