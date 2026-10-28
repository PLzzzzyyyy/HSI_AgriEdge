"""Validator-only release refresh fixtures; no compiler, hardware or service."""
from pathlib import Path
import copy,hashlib,json,sys,tempfile,unittest,zipfile
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'tools'))
import gcs_release as r
import gcs_release_elf as e
import gcs_release_platform as p
from sim.host.test_gcs_release_metadata import BEFORE,AFTER
from sim.host.test_gcs_release_identity import image,SYMTAB

class Refresh(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);q=patch.object(r,'ROOT',self.root);q.start();self.addCleanup(q.stop)
        self.ws=self.root/'build/host/ws';self.old=self.root/'build/host/old';self.new=self.root/'build/host/new';self.out=self.root/'build/host/out'
        self.app=self.ws/r.APP_NAME;(self.app/'src').mkdir(parents=True);(self.app/'Debug').mkdir();self.out.mkdir()
        sources=[dict(path='src/main.cpp',bytes=1,sha256='1'*64),dict(path='src/roi_release.h',bytes=1,sha256='2'*64)]
        self.manifests=[]
        for version,bundle in enumerate((self.old,self.new)):
            (bundle/'app_src').mkdir(parents=True);assets=[]
            for name in ('tools/gcs_release.py','tools/gcs_release_platform.py','tools/gcs_release_elf.py','gcs/unchanged.py'):
                f=bundle/'host_assets'/name;f.parent.mkdir(parents=True,exist_ok=True);f.write_text(str(version) if name.startswith('tools/') else 'unchanged')
                assets.append(r.record(f,name))
            facts=dict(app_id=r.APP_ID,engine_abi=4,source_set_sha256=r.canonical(sources),asset_set_sha256=r.canonical(assets),hardware_xsa_sha256='3'*64,data_set_sha256='4'*64)
            m=dict(app_id=r.APP_ID,release_id=r.canonical(facts),facts=facts,sources=sources,assets=assets,files=[],data_inventory={'files':[],'created':str(version)})
            for name,raw in (('main.cpp',b'int main(){return 0;}'),('roi_release.h',e.identity_bytes(m))):
                f=bundle/'app_src'/name;f.write_bytes(raw);m['files'].append(dict(source='src/'+name,destination='app_src/'+name,bytes=len(raw),sha256=r.sha(f)))
            (bundle/'manifest.json').write_text(json.dumps(m),encoding='utf-8');self.manifests.append(m)
        old,new=self.manifests;self.manifest=new
        for row in old['files']:(self.app/'src'/Path(row['source']).name).write_bytes((self.old/row['destination']).read_bytes())
        for name,raw in (('.project',b'project'),('.cproject',b'flags'),(r.APP_NAME+'.prj',BEFORE),('src/lscript.ld',b'linker')):
            (self.app/name).write_bytes(raw)
        protected=[r.record(self.app/name,str(self.app/name)) for name in ('.project','.cproject',r.APP_NAME+'.prj','src/lscript.ld')]
        protected[2]['normalized_sha256']=hashlib.sha256(e.normalized_prj(BEFORE)).hexdigest()
        sync=dict(result='SYNC_ALL_SOURCES_PASS_NOT_APP_BUILD_NOT_BOARD',release_id=old['release_id'],files=old['files'],app=str(self.app),workspace=str(self.ws),protected=protected,platform={'files':[]})
        (self.old/'sync.json').write_text(json.dumps(sync),encoding='utf-8')
        (self.app/(r.APP_NAME+'.prj')).write_bytes(AFTER)
        (self.app/'Debug'/f'{r.APP_NAME}.elf').write_bytes(image(old))
        (self.app/'Debug/main.o').write_bytes(b'synthetic old object')
    def snapshot(self):return {f.relative_to(self.app).as_posix():f.read_bytes() for f in self.app.rglob('*') if f.is_file()}
    def run_refresh(self,confirmed=True):
        with patch.object(p,'assert_no_build_process'):
            return p.refresh_sources(self.new,self.ws,self.manifest,{'files':[]},self.out,self.old,confirmed)
    def test_requires_current_auto_build_off_before_writes(self):
        before=self.snapshot()
        with self.assertRaises(ValueError):self.run_refresh(False)
        self.assertEqual(before,self.snapshot());self.assertEqual(list(self.out.iterdir()),[])
    def test_refresh_preserves_old_elf_config_and_complete_backup(self):
        before=self.snapshot();result=self.run_refresh()
        self.assertEqual(result['changed_source_names'],['roi_release.h'])
        self.assertTrue(result['user_build_required']);self.assertTrue(result['retained_build_outputs'])
        after=self.snapshot()
        self.assertEqual({k:v for k,v in before.items() if k!='src/roi_release.h'},{k:v for k,v in after.items() if k!='src/roi_release.h'})
        self.assertEqual(after['src/roi_release.h'],(self.new/'app_src/roi_release.h').read_bytes())
        with zipfile.ZipFile(result['backup']['path']) as z:
            for name,raw in before.items():self.assertEqual(z.read(r.APP_NAME+'/'+name),raw)
        self.assertFalse((self.new/'approved_elf.json').exists())
    def test_changed_source_or_user_file_is_not_overwritten(self):
        for name in ('main.cpp','user.cpp'):
            with self.subTest(name=name):
                f=self.app/'src'/name;existed=f.exists();old=f.read_bytes() if existed else None;f.write_bytes(b'user change');before=self.snapshot()
                with self.assertRaises(ValueError):self.run_refresh()
                self.assertEqual(before,self.snapshot())
                if existed:f.write_bytes(old)
                else:f.unlink()
    def test_changed_config_or_old_elf_identity_rejects(self):
        for f in (self.app/'.cproject',self.app/'Debug'/f'{r.APP_NAME}.elf'):
            with self.subTest(path=f.name):
                old=f.read_bytes();f.write_bytes(b'changed');before=self.snapshot()
                with self.assertRaises(ValueError):self.run_refresh()
                self.assertEqual(before,self.snapshot());f.write_bytes(old)
    def test_not_a_general_firmware_or_host_update(self):
        old=self.manifest
        for key in ('source_set_sha256','hardware_xsa_sha256','data_set_sha256'):
            self.manifest=copy.deepcopy(old);self.manifest['facts'][key]='9'*64
            with self.assertRaises(ValueError):self.run_refresh()
        self.manifest=copy.deepcopy(old);self.manifest['assets'][-1]['sha256']='9'*64
        with self.assertRaises(ValueError):self.run_refresh()
        self.manifest=old
    def test_inventory_changes_other_than_observation_time_reject(self):
        self.manifest['data_inventory']['unexpected']='changed'
        with self.assertRaises(ValueError):self.run_refresh()
    def test_matching_bytes_with_wrong_symbol_do_not_authorize_refresh(self):
        import struct
        f=self.app/'Debug'/f'{r.APP_NAME}.elf';data=bytearray(f.read_bytes())
        struct.pack_into('<Q',data,SYMTAB+32,0x100081);f.write_bytes(data);before=self.snapshot()
        with self.assertRaises(ValueError):self.run_refresh()
        self.assertEqual(before,self.snapshot());self.assertEqual(list(self.out.iterdir()),[])
    def test_tampered_frozen_bundle_rejects(self):
        (self.old/'host_assets/tools/gcs_release_elf.py').write_text('tampered')
        before=self.snapshot()
        with self.assertRaises(ValueError):self.run_refresh()
        self.assertEqual(before,self.snapshot())

if __name__=='__main__':unittest.main()
