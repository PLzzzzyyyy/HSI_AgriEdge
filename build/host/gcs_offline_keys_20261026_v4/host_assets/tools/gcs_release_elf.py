"""Read-only audit of the USER-built ABI4 App, full source set and platform.

No compiler, linker, download or serial/UDP use. --register records a reviewed
ELF for a later explicitly scheduled service switch; it does not deploy it.
"""
from pathlib import Path
import xml.etree.ElementTree as ET
from datetime import datetime
import argparse,hashlib,json,re,struct,subprocess,sys
import gcs_release as r

def identity_bytes(m):
    f=m['facts']
    return (f'S2C BUILD app={r.APP_ID} release={m["release_id"]} sources={f["source_set_sha256"]} xsa={f["hardware_xsa_sha256"]}\r\n').encode()

def elf_layout(data):
    if len(data)<64 or data[:6]!=b'\x7fELF\x02\x01':raise ValueError('Require little-endian ELF64')
    if struct.unpack_from('<HH',data,16)!=(2,183):raise ValueError('Require executable AArch64 ELF, not host/old bitness')
    entry,phoff=struct.unpack_from('<QQ',data,24);phentsize,phnum=struct.unpack_from('<HH',data,54)
    if phentsize!=56 or not 0<phnum<256 or phoff+phnum*56>len(data):raise ValueError('Malformed ELF program headers')
    loads=[]
    for i in range(phnum):
        kind,flags,offset,virt,phys,filesz,memsz,align=struct.unpack_from('<IIQQQQQQ',data,phoff+i*56)
        if kind!=1:continue
        if not memsz or filesz>memsz or offset+filesz>len(data) or virt!=phys or phys+memsz>0x7ff00000:
            raise ValueError('ELF LOAD outside low DDR / malformed span')
        if align and align&(align-1):raise ValueError('Non-power-of-two ELF alignment')
        if align and virt%align!=offset%align:raise ValueError('Incongruent ELF LOAD alignment')
        loads.append(dict(address=phys,size=memsz,file_offset=offset,file_bytes=filesz,flags=flags))
    if not loads or not any(x['address']<=entry<x['address']+x['size'] and x['flags']&1 for x in loads):raise ValueError('ELF entry not in executable low DDR')
    for a,b in zip(sorted(loads,key=lambda x:x['address']),sorted(loads,key=lambda x:x['address'])[1:]):
        if a['address']+a['size']>b['address']:raise ValueError('Overlapping ELF LOAD segments')
    return dict(entry=entry,segments=loads)

def audit_identity(data,m):
    """Require one complete, symbol-bound runtime identity, not one file copy.

    Debug metadata is not loaded. A matching string there cannot authorize an
    ELF, nor invalidate its sole runtime identity. All three release gates use
    this parser; no nm dependency, stripped-ELF fallback or file modification.
    """
    layout=elf_layout(data);loads=layout['segments'];expected=identity_bytes(m)
    if (m.get('app_id')!=r.APP_ID or any(not re.fullmatch('[0-9a-f]{64}',value) for value in
        (m['release_id'],m['facts']['source_set_sha256'],m['facts']['hardware_xsa_sha256']))):
        raise ValueError('Invalid expected complete release identity')
    if data[6]!=1 or struct.unpack_from('<I',data,20)[0]!=1 or struct.unpack_from('<H',data,52)[0]!=64:
        raise ValueError('Malformed ELF version/header size')
    shoff=struct.unpack_from('<Q',data,40)[0];shsize,shnum,shstr=struct.unpack_from('<HHH',data,58)
    if shsize!=64 or not 0<shstr<shnum<0xff00 or shoff<64 or shoff+shnum*64>len(data):
        raise ValueError('Complete ELF section/symbol tables required')
    sections=[]
    for i in range(shnum):
        values=struct.unpack_from('<IIQQQQIIQQ',data,shoff+i*64)
        s=dict(zip(('name_offset','type','flags','address','offset','size','link','info','align','entry_size'),values))
        if (i==0 and any(values)) or (s['type']!=8 and s['offset']+s['size']>len(data)):
            raise ValueError('Malformed ELF section file span')
        if s['align'] and s['align']&(s['align']-1):raise ValueError('Malformed ELF section alignment')
        sections.append(s)
    def string(table,offset):
        if table['type']!=3 or not 0<=offset<table['size']:raise ValueError('Malformed ELF string table reference')
        start=table['offset']+offset;end=data.find(b'\0',start,table['offset']+table['size'])
        if end<0:raise ValueError('Unterminated ELF table string')
        return data[start:end]
    for s in sections:s['name']=string(sections[shstr],s['name_offset']).decode('utf-8')
    matches=[];symtabs=0
    for table in sections:
        if table['type'] not in (2,11):continue
        symtabs+=table['type']==2
        if table['entry_size']!=24 or table['size']<24 or table['size']%24 or not 0<table['link']<shnum:
            raise ValueError('Malformed ELF symbol table')
        strings=sections[table['link']]
        for offset in range(table['offset'],table['offset']+table['size'],24):
            name,info,other,index,address,size=struct.unpack_from('<IBBHQQ',data,offset)
            if string(strings,name)==b'gcs_release_identity':
                matches.append(dict(name='gcs_release_identity',info=info,other=other,section_index=index,address=address,size=size))
    if symtabs!=1 or len(matches)!=1:raise ValueError('Unique defined gcs_release_identity symbol required')
    symbol=matches[0];index=symbol['section_index']
    if symbol['info']!=17 or symbol['other']!=0 or not 0<index<shnum or symbol['size']!=len(expected)+1:
        raise ValueError('Wrong ELF release identity symbol type/definition/size')
    section=sections[index];relative=symbol['address']-section['address']
    if (section['type']!=1 or not section['flags']&2 or section['flags']&(1|0x400|0x800) or
        relative<0 or relative+symbol['size']>section['size']):
        raise ValueError('Identity must fit a read-only allocated PROGBITS section')
    offset=section['offset']+relative;end=offset+symbol['size']
    covering=[s for s in loads if s['file_offset']<=offset and end<=s['file_offset']+s['file_bytes'] and
        s['address']+offset-s['file_offset']==symbol['address'] and s['flags']&4]
    if len(covering)!=1 or data[offset:end]!=expected+b'\0':
        raise ValueError('Identity bytes/address not bound to exactly one file-backed PT_LOAD')
    markers=[];previous=None
    for s in sorted(loads,key=lambda x:x['address']):
        chunk=data[s['file_offset']:s['file_offset']+s['file_bytes']]
        if b'UNBOUND_' in chunk:raise ValueError('Unbound loaded ELF identity')
        cursor=0
        while (cursor:=chunk.find(b'S2C BUILD ',cursor))>=0:
            markers.append(s['file_offset']+cursor);cursor+=1
        if previous and previous['address']+previous['file_bytes']==s['address']:
            tail=data[max(previous['file_offset'],previous['file_offset']+previous['file_bytes']-9):previous['file_offset']+previous['file_bytes']]
            if any(marker in tail+chunk[:9] for marker in (b'S2C BUILD ',b'UNBOUND_')):
                raise ValueError('Split/extra loaded ELF identity marker')
        previous=s
    if markers!=[offset] or b'UNBOUND_RELEASE' in data:
        raise ValueError('Missing, duplicate or unbound loaded ELF release identity')
    # A second complete file copy is harmless only when wholly non-allocated
    # and outside every LOAD file range; partial LOAD overlap is not debug.
    copies=[];cursor=0
    while (cursor:=data.find(expected,cursor))>=0:
        if cursor!=offset:
            end_copy=cursor+len(expected)
            if any(cursor<s['file_offset']+s['file_bytes'] and s['file_offset']<end_copy for s in loads if s['file_bytes']):
                raise ValueError('Extra identity intersects an ELF LOAD')
            owners=[s for s in sections if s['type'] not in (0,8) and s['offset']<=cursor and end_copy<=s['offset']+s['size']]
            if not owners or any(s['flags']&2 for s in owners):raise ValueError('Extra identity is not non-loaded metadata')
            copies.append(dict(file_offset=cursor,sections=[s['name'] for s in owners]))
        cursor+=1
    return dict(symbol=symbol,section=section['name'],file_offset=offset,loaded_identity_count=1,
        nonloaded_copies=len(copies),nonloaded_metadata=copies,layout=layout)

def symbols(text):
    records=[]
    for line in text.splitlines():
        match=re.match(r'^([0-9a-fA-F]+)\s+([0-9a-fA-F]+)\s+(\S)\s+(.+)$',line)
        if match:records.append(dict(address=int(match[1],16),size=int(match[2],16),kind=match[3],name=match[4]))
    return records

def audit_buffers(records,segments,input_stride):
    arrays=dict(cube=491428080,cls=10584,pos=63504,weights=480576,patch=52920,input=4*input_stride,
        output=64,probe_output=1920,results=446500*12)
    checked=[]
    def select(name,minimum,maximum=None,alignment=1):
        matches=[x for x in records if x['name']==name]
        if len(matches)!=1:raise ValueError('ELF buffer missing/ambiguous: '+name)
        x=matches[0];maximum=minimum if maximum is None else maximum
        if not minimum<=x['size']<=maximum or x['address']%alignment or x['address']+x['size']>0x7ff00000:
            raise ValueError('ELF buffer size/alignment/low-DDR contract: '+name)
        if not any(s['address']<=x['address'] and x['address']+x['size']<=s['address']+s['size'] and s['flags']&2 for s in segments):
            raise ValueError('Buffer not fully within writable LOAD: '+name)
        checked.append(x)
    for name,size in arrays.items():select('s2c::(anonymous namespace)::'+name,size,alignment=1 if name=='results' else 64)
    select('(anonymous namespace)::g_frame',1920*1080*4,alignment=256)
    select('(anonymous namespace)::result_store',4*2097152,4*2097152+4096)
    select('(anonymous namespace)::model_store',48*596368,49*596368+8192)
    for a,b in zip(sorted(checked,key=lambda x:x['address']),sorted(checked,key=lambda x:x['address'])[1:]):
        if a['address']+a['size']>b['address']:raise ValueError('CPU/PL/DP buffers overlap')
    return checked

def build_commands(text,files):
    required={'-O2','-ffp-contract=off','-mcpu=cortex-a53','-std=c++14','-Wall','-Wextra','-Werror'}
    if re.search(r'(?im)(?:^|\s)(?:fatal error:|error:|warning:)',text):raise ValueError('Application Build log contains errors/warnings')
    result={}
    for row in files:
        name=Path(row['source']).name
        if not name.endswith('.cpp'):continue
        lines=[line for line in text.splitlines() if 'aarch64-none-elf-g++' in line and name in line and re.search(r'(?:^|\s)-c(?:\s|$)',line)]
        if len(lines)!=1:raise ValueError('Need one complete user compilation record per source: '+name)
        line=lines[0]
        if not all(flag in line.split() for flag in required) or '-ffast-math' in line or '-Ofast' in line:
            raise ValueError('Wrong application numeric/CPU/compiler flags: '+name)
        result[name]=line
    if not any('aarch64-none-elf-g++' in line and r.APP_NAME+'.elf' in line and '-Wl,--gc-sections' in line for line in text.splitlines()):
        raise ValueError('Final user link command absent')
    return result

def normalized_prj(data):
    """Ignore only Vitis's empty Debug bookkeeping, not actual build options."""
    pattern=rb'(<configuration name="Debug" id="[^"]+")(?: dirty="(?:true|false)")?>(.*?)</configuration>'
    matches=list(re.finditer(pattern,data,re.S))
    if not matches:return data
    if len(matches)!=1:raise ValueError('Ambiguous Debug configuration')
    root=ET.fromstring(data)
    debug=[x for x in root.findall('configuration') if x.get('name')=='Debug']
    if len(debug)!=1:raise ValueError('Ambiguous Debug XML scope')
    last=debug[0].findall('lastBuildOptions')
    if len(last)>1:raise ValueError('Duplicate Debug lastBuildOptions')
    match=matches[0];body=match[2]
    if last:
        node=last[0]
        expected={'{http://www.w3.org/2001/XMLSchema-instance}type':'sdkproject:SdkOptions'}
        if node.attrib!=expected or len(node) or (node.text or '').strip():
            raise ValueError('Nonempty or unexpected Debug lastBuildOptions')
        body,count=re.subn(rb'(?m)^[ \t]*<lastBuildOptions xsi:type="sdkproject:SdkOptions"/>\r?\n',b'',body)
        if count!=1:raise ValueError('Unexpected Debug bookkeeping serialization')
    return data[:match.start()]+match[1]+b'>'+body+b'</configuration>'+data[match.end():]

def audit_feature_symbols(rows):
    # Full-scene main uses these functions; unused legacy display_update is GC'd.
    required=('gcs_release_identity','tt_m3a_run(','tt_m3a_load_weights(','tt_m3a_set_wait_service(',
        's2c::acquire_sd_boot_id(','s2c::step_task(','s2c::probe_model(',
        's2c::display_init(','s2c::display_scene_begin(','s2c::display_scene_append(','s2c::display_scene_update(',
        'XDpPsu_CfgInitialize','XDpDma_DisplayGfxFrameBuffer',
        's2c::Models::activate(','s2c::ModelSd::scan(','XTt_engine_Get_cycles')
    missing=[name for name in required if not any(x['name'].startswith(name) for x in rows)]
    if missing:raise ValueError('Required new ELF feature symbols missing: '+str(missing))
    return list(required)

def verify_sync(bundle,m):
    sync=json.loads((bundle/'sync.json').read_text(encoding='utf-8'))
    if sync.get('result')!='SYNC_ALL_SOURCES_PASS_NOT_APP_BUILD_NOT_BOARD' or sync.get('release_id')!=m['release_id'] or sync['files']!=m['files']:
        raise ValueError('Complete matching source synchronization receipt required')
    app=Path(sync['app']).resolve()
    if app!=Path(sync['workspace']).resolve()/r.APP_NAME or not app.is_relative_to(r.ROOT/'build/host'):raise ValueError('Not the isolated new App')
    if {p.name for p in (app/'src').iterdir() if p.suffix in ('.cpp','.c','.h')}!={Path(x['source']).name for x in m['files']}:raise ValueError('Incomplete or extra App sources')
    protected=[]
    for row in m['files']:
        p=app/'src'/Path(row['source']).name
        if r.sha(p)!=row['sha256']:raise ValueError('User Build sources changed: '+p.name)
        protected.append(r.record(p,str(p)))
    for row in sync['protected']:
        p=Path(row['path'])
        if r.sha(p)!=row['sha256']:
            if p.suffix!='.prj' or hashlib.sha256(normalized_prj(p.read_bytes())).hexdigest()!=row.get('normalized_sha256'):
                raise ValueError('App config/linker changed: '+p.name)
        protected.append(r.record(p,str(p)))
    for row in sync['platform']['files']:
        if r.sha(row['path'])!=row['sha256']:raise ValueError('Generated platform changed after synchronization')
        protected.append(row)
    return sync,protected

def audit(bundle,build_log,out,register=False):
    bundle=r.local_output(bundle);out=r.local_output(out);build_log=Path(build_log).resolve()
    if out.exists():raise ValueError('New audit evidence directory required')
    m=r.inspect(bundle);sync,protected=verify_sync(bundle,m);app=Path(sync['app']);elf=app/'Debug'/(r.APP_NAME+'.elf')
    data=elf.read_bytes();identity=audit_identity(data,m)
    commands=build_commands(build_log.read_text(encoding='utf-8',errors='strict'),m['files']);layout=identity['layout']
    out.mkdir(parents=True,exist_ok=False)
    receipt=dict(result='RUNNING',scope='USER_BUILD_ELF_AUDIT_NOT_DOWNLOAD_OR_BOARD',app_id=r.APP_ID,release_id=m['release_id'],
        source_set_sha256=m['facts']['source_set_sha256'],hardware_xsa_sha256=m['facts']['hardware_xsa_sha256'],
        elf=r.record(elf,str(elf)),build_log=r.record(build_log,str(build_log)),compile_commands=commands,layout=layout,identity=identity,
        sync_sha256=r.sha(bundle/'sync.json'),protected_files=protected)
    def save():(out/'audit.json').write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf-8')
    save()
    try:
        argv=[str(r.BIN/'aarch64-none-elf-nm.exe'),'-S','-C','--defined-only',str(elf)]
        result=subprocess.run(argv,capture_output=True,timeout=60);(out/'symbols.txt').write_bytes(result.stdout);(out/'symbols.stderr').write_bytes(result.stderr)
        if result.returncode:raise ValueError('Cannot read new ELF symbols')
        rows=symbols(result.stdout.decode('utf-8'));text=(r.ROOT/'src/hls/tt_engine_regs.h').read_text(encoding='utf-8')
        stride=re.search(r'#define\s+TT_ENGINE_IN_STRIDE\s+(\d+)',text)
        if not stride:raise ValueError('Missing input stride contract')
        receipt['buffers']=audit_buffers(rows,layout['segments'],int(stride[1]))
        required=audit_feature_symbols(rows)
        protected.append(r.record(build_log,str(build_log)));protected.append(r.record(bundle/'sync.json',str(bundle/'sync.json')))
        receipt.update(result='ELF_CANDIDATE_PASS',required_symbols=list(required),finished=datetime.now().isoformat());save()
        if register:
            destination=bundle/'approved_elf.json'
            if destination.exists():shutil_copy=destination.read_bytes();(out/'previous_approved_elf.json').write_bytes(shutil_copy)
            destination.write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf-8')
    except Exception as exc:receipt.update(result='FAIL',error=str(exc));save();raise
    return receipt
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--bundle',type=Path,default=r.BUNDLE);p.add_argument('--build-log',type=Path,required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--register',action='store_true')
    a=p.parse_args();result=audit(a.bundle,a.build_log,a.out,a.register);print(json.dumps({k:result[k] for k in ('result','app_id','release_id','elf')},indent=2))
