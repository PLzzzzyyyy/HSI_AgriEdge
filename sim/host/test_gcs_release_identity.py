"""Loaded ELF identity regressions; synthetic files, never Build or deploy."""
from pathlib import Path
import json,struct,sys,tempfile,unittest
from contextlib import ExitStack
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'tools'))
import gcs_release as r
import gcs_release_elf as e

MANIFEST=dict(app_id=r.APP_ID,release_id='1'*64,
    facts=dict(source_set_sha256='2'*64,hardware_xsa_sha256='3'*64),files=[],assets=[])
LOAD=0x1000;IDENTITY=0x1080;DEBUG=0x1700;STRTAB=0x1900;SYMTAB=0x1a00;SHSTR=0x1b00;SECTIONS=0x1c00

def image(manifest=MANIFEST,debug=True):
    """Real ELF64 section/symbol/LOAD relationships, not an identity-only blob."""
    data=bytearray(0x2000);data[:7]=b'\x7fELF\x02\x01\x01'
    struct.pack_into('<HHIQQQIHHHHHH',data,16,2,183,1,0x100000,64,SECTIONS,0,64,56,1,64,6,5)
    struct.pack_into('<IIQQQQQQ',data,64,1,5,LOAD,0x100000,0x100000,0x600,0x800,0x1000)
    identity=e.identity_bytes(manifest)+b'\0';data[IDENTITY:IDENTITY+len(identity)]=identity
    if debug:data[DEBUG:DEBUG+len(identity)]=identity
    strings=b'\0gcs_release_identity\0';data[STRTAB:STRTAB+len(strings)]=strings
    names=b'\0.rodata\0.debug_info\0.strtab\0.symtab\0.shstrtab\0';data[SHSTR:SHSTR+len(names)]=names
    sections=[(0,0,0,0,0,0,0,0,0,0),
        (names.index(b'.rodata'),1,2,0x100080,IDENTITY,len(identity),0,0,8,0),
        (names.index(b'.debug_info'),1,0,0,DEBUG,len(identity) if debug else 0,0,0,1,0),
        (names.index(b'.strtab'),3,0,0,STRTAB,len(strings),0,0,1,0),
        (names.index(b'.symtab'),2,0,0,SYMTAB,48,3,1,8,24),
        (names.index(b'.shstrtab'),3,0,0,SHSTR,len(names),0,0,1,0)]
    for i,s in enumerate(sections):struct.pack_into('<IIQQQQIIQQ',data,SECTIONS+64*i,*s)
    struct.pack_into('<IBBHQQ',data,SYMTAB+24,1,17,0,1,0x100080,len(identity))
    return data

class LoadedIdentity(unittest.TestCase):
    def test_debug_copy_is_not_a_second_runtime_identity(self):
        data=image();before=bytes(data);result=e.audit_identity(data,MANIFEST)
        self.assertEqual(result['file_offset'],IDENTITY)
        self.assertEqual(result['symbol']['size'],len(e.identity_bytes(MANIFEST))+1)
        self.assertEqual(result['nonloaded_copies'],1)
        self.assertEqual(bytes(data),before)
        self.assertEqual(e.audit_identity(image(debug=False),MANIFEST)['nonloaded_copies'],0)

    def test_loaded_duplicate_wrong_binding_and_unbound_rejected(self):
        for extra in (e.identity_bytes(MANIFEST),e.identity_bytes(MANIFEST).replace(b'1'*64,b'4'*64),
                      b'S2C BUILD broken',b'UNBOUND_RELEASE',b'UNBOUND_SOURCES',b'UNBOUND_XSA'):
            with self.subTest(extra=extra[:40]):
                data=image();data[0x1300:0x1300+len(extra)]=extra
                with self.assertRaises(ValueError):e.audit_identity(data,MANIFEST)
        for offset in (IDENTITY,IDENTITY+20,IDENTITY+len(e.identity_bytes(MANIFEST))):
            with self.subTest(offset=offset):
                data=image();data[offset]^=1
                with self.assertRaises(ValueError):e.audit_identity(data,MANIFEST)

    def test_missing_ambiguous_wrong_or_out_of_range_symbol_rejected(self):
        changes=((SYMTAB+24,'I',0),(SYMTAB+28,'B',18),(SYMTAB+29,'B',2),
                 (SYMTAB+30,'H',0),(SYMTAB+30,'H',2),(SYMTAB+30,'H',0xfff1),
                 (SYMTAB+32,'Q',0x100081),(SYMTAB+40,'Q',242),(SYMTAB+40,'Q',244))
        for offset,fmt,value in changes:
            with self.subTest(offset=offset,value=value):
                data=image();struct.pack_into('<'+fmt,data,offset,value)
                with self.assertRaises(ValueError):e.audit_identity(data,MANIFEST)
        data=image();data[SYMTAB+48:SYMTAB+72]=data[SYMTAB+24:SYMTAB+48]
        struct.pack_into('<Q',data,SECTIONS+4*64+32,72)
        with self.assertRaises(ValueError):e.audit_identity(data,MANIFEST)

    def test_malformed_elf_sections_tables_and_load_mapping_rejected(self):
        changes=((6,'B',0),(20,'I',0),(40,'Q',0xfffffff0),(52,'H',63),(58,'H',63),
                 (60,'H',0),(62,'H',50),(64+32,'Q',0x80+242),
                 (SECTIONS+64+4,'I',8),(SECTIONS+64+8,'Q',0),
                 (SECTIONS+64+16,'Q',0x100081),(SECTIONS+64+24,'Q',0xfffffff0),
                 (SECTIONS+4*64+40,'I',50),(SECTIONS+4*64+56,'Q',23),
                 (SYMTAB+24,'I',10000))
        for offset,fmt,value in changes:
            with self.subTest(offset=offset,value=value):
                data=image();struct.pack_into('<'+fmt,data,offset,value)
                with self.assertRaises(ValueError):e.audit_identity(data,MANIFEST)
        for data in (image()[:40],image()[:-1500]):
            with self.assertRaises(ValueError):e.audit_identity(data,MANIFEST)
        data=image();struct.pack_into('<H',data,56,2)
        struct.pack_into('<IIQQQQQQ',data,120,1,5,LOAD,0x200000,0x200000,0x600,0x800,0x1000)
        with self.assertRaises(ValueError):e.audit_identity(data,MANIFEST)

class IdentityEntryPoints(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.root=Path(tmp.name)
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(r,'ROOT',self.root))
        self.bundle=self.root/'build/host/bundle';self.bundle.mkdir(parents=True)
        self.app=self.root/'build/host/ws'/r.APP_NAME;(self.app/'Debug').mkdir(parents=True)
        self.elf=self.app/'Debug'/(r.APP_NAME+'.elf');self.elf.write_bytes(image())
        self.log=self.root/'build.log';self.log.write_text('separately tested compile log',encoding='utf-8')
        (self.bundle/'sync.json').write_text('{}',encoding='utf-8')
        regs=self.root/'src/hls/tt_engine_regs.h';regs.parent.mkdir(parents=True)
        regs.write_text('#define TT_ENGINE_IN_STRIDE 31808\n',encoding='utf-8')
        self.stack.enter_context(patch.object(r,'inspect',return_value=MANIFEST))
        self.stack.enter_context(patch.object(e,'verify_sync',side_effect=lambda *a:({'app':str(self.app)},[])))
        self.stack.enter_context(patch.object(e,'build_commands',return_value={}))
        self.stack.enter_context(patch.object(e,'audit_buffers',return_value=[]))
        self.stack.enter_context(patch.object(e,'audit_feature_symbols',return_value=[]))
        from subprocess import CompletedProcess
        self.stack.enter_context(patch.object(e.subprocess,'run',return_value=CompletedProcess([],0,b'',b'')))

    def production_receipt(self):
        a=dict(result='ELF_CANDIDATE_PASS',app_id=r.APP_ID,release_id=MANIFEST['release_id'],
            source_set_sha256=MANIFEST['facts']['source_set_sha256'],hardware_xsa_sha256=MANIFEST['facts']['hardware_xsa_sha256'],
            elf=r.record(self.elf,str(self.elf)),sync_sha256=r.sha(self.bundle/'sync.json'),build_log=r.record(self.log,str(self.log)),
            protected_files=[r.record(self.log,str(self.log)),r.record(self.bundle/'sync.json',str(self.bundle/'sync.json'))])
        (self.bundle/'approved_elf.json').write_text(json.dumps(a),encoding='utf-8')

    def test_debug_copy_accepted_by_formal_and_production_gates(self):
        result=e.audit(self.bundle,self.log,self.root/'build/host/audit')
        self.assertEqual(result['result'],'ELF_CANDIDATE_PASS')
        self.production_receipt();self.assertEqual(r.audited_elf(self.bundle),self.bundle/'approved_elf.json')

    def test_both_entrypoints_reject_wrong_symbol_even_if_bytes_match(self):
        data=image(debug=False);struct.pack_into('<Q',data,SYMTAB+32,0x100081);self.elf.write_bytes(data)
        with self.assertRaises(ValueError):e.audit(self.bundle,self.log,self.root/'build/host/audit')
        self.production_receipt()
        with self.assertRaises(ValueError):r.audited_elf(self.bundle)

if __name__=='__main__':unittest.main()
