"""Check a PYNQ ip_dict against a reusable overlay interface contract.

Metadata mode needs only Python's standard library. PYNQ mode constructs
Overlay(download=False); this tool never downloads, starts an IP or reads MMIO.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys


def number(value):
    if isinstance(value,bool): raise ValueError('Boolean is not an address range')
    result=int(value,0) if isinstance(value,str) else int(value)
    if isinstance(value,float) and result!=value:raise ValueError('Fractional address range')
    return result


def check(contract, metadata):
    if contract.get('schema')!=1 or not isinstance(contract.get('ips'),dict) or not contract['ips']:
        raise ValueError('Contract requires schema=1 and nonempty ips')
    if not isinstance(metadata,dict):raise ValueError('ip_dict must be an object')
    checked=[]
    for name,expected in contract['ips'].items():
        if not isinstance(expected,dict):raise ValueError('Invalid expected IP '+name)
        actual=metadata.get(name)
        if not isinstance(actual,dict):raise ValueError('Missing IP '+name)
        expected_type=expected.get('type')
        if not isinstance(expected_type,str) or len(expected_type.split(':'))!=4:
            raise ValueError('Explicit VLNV required for '+name)
        if actual.get('type')!=expected_type:raise ValueError('VLNV mismatch for '+name)
        minimum=number(expected.get('min_addr_range',0))
        size=number(actual.get('addr_range',0));address=number(actual.get('phys_addr',-1))
        if minimum<=0 or size<minimum or address<0 or address%4:
            raise ValueError('Invalid/insufficient AXI address range for '+name)
        parameters=actual.get('parameters',{})
        for key,value in expected.get('parameters',{}).items():
            if str(parameters.get(key))!=str(value):raise ValueError('Parameter mismatch '+name+'/'+key)
        checked.append({'name':name,'type':expected_type,'phys_addr':address,'addr_range':size})
    return checked


def inspect(contract,ip_dict=None,bitfile=None,overlay_class=None):
    if (ip_dict is None)==(bitfile is None):raise ValueError('Select exactly one metadata source')
    if bitfile is not None:
        bit=Path(bitfile).resolve();hwh=bit.with_suffix('.hwh')
        assets=contract.get('assets',{})
        for kind,path in [('bit',bit),('hwh',hwh)]:
            expected=assets.get(kind+'_sha256')
            if not isinstance(expected,str) or len(expected)!=64:raise ValueError('Pin '+kind+'_sha256 for PYNQ mode')
            actual=hashlib.sha256(path.read_bytes()).hexdigest()
            if actual!=expected.lower():raise ValueError('Asset SHA256 mismatch: '+kind)
        if overlay_class is None:
            from pynq import Overlay
            overlay_class=Overlay
        overlay=overlay_class(str(bit),download=False)
        metadata=overlay.ip_dict
        scope='PYNQ_METADATA_ONLY_NO_DOWNLOAD_OR_MMIO'
    else:
        metadata=ip_dict;scope='OFFLINE_IP_DICT_CONTRACT_NOT_BOARD_VALIDATION'
    return {'result':'PASS','scope':scope,'ips':check(contract,metadata)}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--contract',required=True)
    group=parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--ip-dict')
    group.add_argument('--bitfile')
    args=parser.parse_args()
    try:
        contract=json.loads(Path(args.contract).read_text('utf-8'))
        data=None if args.ip_dict is None else json.loads(Path(args.ip_dict).read_text('utf-8'))
        result=inspect(contract,data,args.bitfile)
    except (ValueError,KeyError,TypeError,OSError,ImportError,RuntimeError) as exc:
        print(json.dumps({'result':'FAIL','reason':str(exc)},ensure_ascii=False))
        return 1
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0

if __name__=='__main__':sys.exit(main())
