"""Synthetic release-gate regressions. No App Build, card, network or device."""
from pathlib import Path
import copy,json,struct,sys,tempfile,unittest,uuid
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2];sys.path[:0]=[str(ROOT/'tools'),str(ROOT/'gcs')]
import gcs_release as r
import gcs_release_elf as elf
import gcs_release_platform as platform
import board_release as contract
import uart_capture as uart

EXPECTED=dict(app_id=contract.APP_ID,release_id='1'*64,source_set_sha256='2'*64,hardware_xsa_sha256='3'*64)
BUILD=f'S2C BUILD app={contract.APP_ID} release={"1"*64} sources={"2"*64} xsa={"3"*64}\r\n'
IDENTITY='S2C IDENTITY source=sd-journal boot_id=12345678 generation=1 nonce=1234567887654321 abi=4\r\n'
READY=f'S2C READY boot_id=12345678 registry=6 scan_ok=1 scenes=3 roi=any banks=1 UDP=5010 app={contract.APP_ID}\r\n'

class Release(unittest.TestCase):
    def test_candidate_default_and_existing_bundle_are_isolated(self):
        self.assertEqual(r.BUNDLE,ROOT/'build/host/gcs_r1_abi4_release_v6')
        with tempfile.TemporaryDirectory(dir=ROOT/'build/host') as tmp:
            bundle=Path(tmp);marker=bundle/'manifest.json';marker.write_bytes(b'keep existing bundle')
            with patch.object(r,'hardware',side_effect=AssertionError('No hardware work for existing bundle')):
                with self.assertRaisesRegex(ValueError,'Refuse existing release bundle'):r.prepare(bundle)
            self.assertEqual(marker.read_bytes(),b'keep existing bundle')
            self.assertEqual(list(bundle.iterdir()),[marker])
    def test_complete_source_and_assets_not_legacy_24(self):
        rows=r.source_records();names={Path(x['path']).name for x in rows}
        self.assertEqual(len(rows),35)
        self.assertEqual({x['path'] for x in rows},{
            'src/ps/s2c_roi_app/main.cpp','src/ps/s2c_roi_app/s1b_profile.h',
            'src/ps/s2c_roi_app/roi_protocol.h','src/ps/s2c_roi_app/roi_protocol.cpp',
            'src/ps/s2c_roi_app/roi_runtime.h','src/ps/s2c_roi_app/roi_runtime.cpp',
            'src/ps/s2c_roi_app/roi_canvas.h','src/ps/s2c_roi_app/roi_canvas.cpp',
            'src/ps/s2c_roi_app/roi_display.h','src/ps/s2c_roi_app/roi_display.cpp',
            'src/ps/s2c_roi_app/roi_labels.h','src/ps/s2c_roi_app/roi_results.h',
            'src/ps/s2c_roi_app/roi_models.h','src/ps/s2c_roi_app/roi_models.cpp',
            'src/ps/s2c_roi_app/roi_model_sd.h','src/ps/s2c_roi_app/roi_model_sd.cpp',
            'src/ps/s2c_roi_app/roi_timing.h','src/ps/s2c_roi_app/roi_board_log.h',
            'src/ps/s2c_roi_app/roi_boot_id.h','src/ps/s2c_roi_app/roi_boot_id.cpp',
            'src/ps/s2c_roi_app/roi_boot_sd.cpp','src/ps/s2c_roi_app/roi_release.h',
            'src/ps/tt_m3a.cpp','src/ps/tt_m3a.h','src/ps/tt_net.cpp','src/ps/tt_net.h',
            'src/ps/tt_hw.h','src/ps/tt_measure.h','src/ps/system/m3a_roi.cpp',
            'src/ps/system/m3a_roi.h','src/ps/system/m3a_sd.cpp','src/ps/system/m3a_sd.h',
            'src/ps/system/m3a_app.h','src/ps/system/s1b/legacy_traps.cpp',
            'src/hls/tt_engine_regs.h'})
        self.assertNotIn('boot_id.cpp',names)
        assets=r.runtime_assets();self.assertIn('gcs/board_release.py',{x['path'] for x in assets})
        self.assertIn('tools/gcs_release_elf.py',{x['path'] for x in assets})
    def test_unbound_source_template_is_only_rendered_in_bundle(self):
        raw=(ROOT/'src/ps/s2c_roi_app/roi_release.h').read_text()
        rendered=r.render_header(raw,EXPECTED,EXPECTED['release_id']).decode()
        self.assertIn('S2C_RELEASE_BOUND 1',rendered);self.assertNotIn('UNBOUND_',rendered)
        self.assertIn('S2C_RELEASE_BOUND 0',raw)
        with self.assertRaises(ValueError):r.render_header(raw.replace('UNBOUND_XSA','other'),EXPECTED,EXPECTED['release_id'])
    def test_path_traversal_and_existing_user_workspace_refused(self):
        for path in ('../src/main.cpp','C:/vitis','/src/a','a\\b'):
            with self.assertRaises(ValueError):r.safe_relative(path)
        for path in (ROOT,ROOT/'vitis/s2c_roi_app'):
            with self.assertRaises(ValueError):r.local_output(path)
    def test_hardware_failure_does_not_prepare_or_sync(self):
        out=ROOT/'build/host'/('release_negative_'+uuid.uuid4().hex)
        with patch.object(r,'hardware',side_effect=ValueError('not routed')):
            with self.assertRaisesRegex(ValueError,'not routed'):r.prepare(out)
        self.assertFalse(out.exists())
    def test_real_sd_identity_requires_reviewed_build_first(self):
        claimed=[];p=uart.SdIdentity(0,claimed.append,EXPECTED)
        self.assertEqual(p.feed((BUILD+IDENTITY+READY).encode(),1),[])
        self.assertEqual(p.state,'ready');self.assertEqual(p.build,EXPECTED);self.assertEqual(claimed,[0x12345678])
        for text in (IDENTITY+READY,BUILD.replace('1'*64,'4'*64)+IDENTITY+READY,BUILD+BUILD+IDENTITY+READY,BUILD+IDENTITY+READY.replace(contract.APP_ID,contract.LEGACY_APP_ID)):
            p=uart.SdIdentity(0,lambda b:None,EXPECTED);self.assertEqual(p.feed(text.encode(),1),[]);self.assertEqual(p.state,'error')
    def test_missing_or_old_audit_cannot_open_uart(self):
        with tempfile.TemporaryDirectory() as tmp,patch('serial.Serial',side_effect=AssertionError('no serial')):
            c=uart.Capture(tmp,lambda b:None)
            with self.assertRaises(ValueError):c.start('COM5',115200,True)
            audit=Path(tmp)/'old.json';audit.write_text(json.dumps(dict(result='NEW_ELF_READ_ONLY_PASS_NOT_BOARD_TEST',app_id='scene_probe_s3_r1')))
            with self.assertRaises(ValueError):c.start('COM5',115200,True,str(audit))
            self.assertFalse(c.snapshot()['active']);self.assertIsNone(c.out)
    def test_build_identity_parser_no_duplicate_or_missing_fields(self):
        self.assertEqual(contract.uart_build(BUILD,EXPECTED),EXPECTED)
        for text in ('',BUILD+BUILD,BUILD.replace('xsa=','hardware='),BUILD.replace(contract.APP_ID,contract.LEGACY_APP_ID)):
            with self.assertRaises(ValueError):contract.uart_build(text,EXPECTED)
    def test_current_app_task_evidence_is_bound_to_reviewed_release(self):
        from sim.host.test_gcs_model_business import fixture
        import gcs_task_verify
        with tempfile.TemporaryDirectory() as tmp:
            job,path=fixture(Path(tmp),'honghu')
            text=path.read_text().replace(contract.LEGACY_APP_ID,contract.APP_ID)
            path.write_text(BUILD+text)
            with self.assertRaises(OSError):gcs_task_verify.verify(job.out,path)
            audit=job.out/'elf_audit.json';audit.write_text(json.dumps(dict(result='ELF_CANDIDATE_PASS',**EXPECTED)))
            result=gcs_task_verify.verify(job.out,path);self.assertEqual(result['release_build'],EXPECTED)
            self.assertTrue(result['data_acceptance']);self.assertFalse(result['batch_acceptance'])
            audit.write_text(json.dumps(dict(result='ELF_CANDIDATE_PASS',**{**EXPECTED,'release_id':'4'*64})))
            with self.assertRaises(ValueError):gcs_task_verify.verify(job.out,path)
    def test_bsp_only_expected_generated_driver_revision_can_change(self):
        old=platform.mss(r.BASE_BSP/'system.mss');new=copy.deepcopy(old)
        new[('DRIVER','tt_engine_0')]['DRIVER_VER']='4.0'
        platform.compatible_mss(old,new)
        for key,field,value in ((('LIBRARY','lwip211'),'phy_link_speed','CONFIG_LINKSPEED_AUTODETECT'),(('DRIVER','psu_dp'),'DRIVER_NAME','avbuf'),(('LIBRARY','xilffs'),'use_lfn','0')):
            wrong=copy.deepcopy(new);wrong[key][field]=value
            with self.assertRaises(ValueError):platform.compatible_mss(old,wrong)
    def test_build_log_requires_all_sources_and_numeric_flags(self):
        files=[{'source':'a.cpp'},{'source':'b.cpp'},{'source':'c.h'}]
        flags='-O2 -ffp-contract=off -mcpu=cortex-a53 -std=c++14 -Wall -Wextra -Werror -c'
        text='\n'.join(f'aarch64-none-elf-g++ {flags} ../src/{name}' for name in ('a.cpp','b.cpp'))+'\naarch64-none-elf-g++ -Wl,--gc-sections -o gcs_r1_abi4_app.elf a.o b.o\n'
        self.assertEqual(len(elf.build_commands(text,files)),2)
        for wrong in (text.replace('-O2','-Ofast'),text.replace('-ffp-contract=off',''),text.replace('../src/b.cpp','../src/c.cpp'),text+'warning: changed app\n'):
            with self.assertRaises(ValueError):elf.build_commands(wrong,files)

class ElfBoundary(unittest.TestCase):
    def image(self):
        data=bytearray(128);data[:6]=b'\x7fELF\x02\x01';struct.pack_into('<HH',data,16,2,183)
        struct.pack_into('<QQ',data,24,0x100000,64);struct.pack_into('<HH',data,54,56,1)
        struct.pack_into('<IIQQQQQQ',data,64,1,7,0,0x100000,0x100000,128,0x30000000,4096)
        return data
    def test_a53_low_ddr_segments_and_entry(self):
        image=self.image();layout=elf.elf_layout(image);self.assertEqual(len(layout['segments']),1)
        for offset,fmt,value in ((18,'H',62),(24,'Q',0x90000000),(96,'Q',0x100000000),(104,'Q',0x80000000),(112,'Q',3)):
            data=bytearray(image);struct.pack_into('<'+fmt,data,offset,value)
            with self.assertRaises(ValueError):elf.elf_layout(data)
    def buffers(self):
        sizes=dict(cube=491428080,cls=10584,pos=63504,weights=480576,patch=52920,input=4*31808,output=64,probe_output=1920,results=446500*12)
        rows=[];address=0x100000
        for name,size in sizes.items():
            address=(address+255)&~255;rows.append(dict(name='s2c::(anonymous namespace)::'+name,address=address,size=size));address+=size
        for name,size in (('g_frame',1920*1080*4),('result_store',4*2097152+256),('model_store',48*596368+1024)):
            address=(address+255)&~255;rows.append(dict(name='(anonymous namespace)::'+name,address=address,size=size));address+=size
        return rows
    def test_all_new_cpu_dma_dp_spans_and_disjointness(self):
        rows=self.buffers();segments=[dict(address=0x100000,size=0x30000000,flags=7)]
        self.assertEqual(len(elf.audit_buffers(rows,segments,31808)),12)
        for index,field,value in ((0,'size',243794880),(7,'size',128),(5,'address',0x100000000),(1,'address',0x100000),(10,'size',2097152)):
            wrong=copy.deepcopy(rows);wrong[index][field]=value
            with self.assertRaises(ValueError):elf.audit_buffers(wrong,segments,31808)

class UserPlatformBoundary(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.root_patch=patch.object(r,'ROOT',self.root);self.root_patch.start();self.addCleanup(self.root_patch.stop)
        self.ws=self.root/'build/host/user_workspace';self.bundle=self.root/'build/host/bundle';self.out=self.root/'build/host/receipt'
    def fixture(self):
        app=self.ws/r.APP_NAME;src=app/'src';src.mkdir(parents=True);self.out.mkdir(parents=True)
        plat=self.ws/r.PLATFORM_NAME/'export'/r.PLATFORM_NAME/(r.PLATFORM_NAME+'.xpfm');plat.parent.mkdir(parents=True);plat.write_text('synthetic platform')
        (app/(r.APP_NAME+'.prj')).write_text(f'<SdkProject os="standalone" cpuInstance="psu_cortexa53_0" cpu="standalone_domain" platform="{plat.as_posix()}"/>')
        (app/'.project').write_text('synthetic project');(app/'.cproject').write_text('<project/>');(src/'lscript.ld').write_text('synthetic reviewed linker')
        linker=self.bundle/'host_assets/vitis/s2c_roi_app/src/lscript.ld';linker.parent.mkdir(parents=True);linker.write_text('synthetic reviewed linker')
        (self.bundle/'app_src').mkdir();source=self.bundle/'app_src/entry.cpp';source.write_text('int entry(){return 0;}')
        self.manifest=dict(release_id='1'*64,files=[dict(source='entry.cpp',destination='app_src/entry.cpp',sha256=r.sha(source))])
        return app,src
    def test_missing_user_workspace_does_not_create_or_build(self):
        with patch.object(platform.subprocess,'run',side_effect=AssertionError('no tools')):
            with self.assertRaises(ValueError):platform.inspect_user_platform(self.bundle,self.ws,self.out,self.root/'absent.log')
        self.assertFalse(self.ws.exists());self.assertFalse(self.out.exists())
    def test_source_sync_is_confirmed_and_does_not_edit_metadata(self):
        app,src=self.fixture();before={p.name:p.read_bytes() for p in app.iterdir() if p.is_file()}
        with patch.object(platform,'assert_no_build_process'):
            with self.assertRaises(ValueError):platform.sync_sources(self.bundle,self.ws,self.manifest,{},self.out)
            self.assertFalse((src/'entry.cpp').exists())
            result=platform.sync_sources(self.bundle,self.ws,self.manifest,{},self.out,True)
        self.assertEqual(result['result'],'SYNC_ALL_SOURCES_PASS_NOT_APP_BUILD_NOT_BOARD')
        self.assertEqual(before,{p.name:p.read_bytes() for p in app.iterdir() if p.is_file()})
        self.assertTrue((self.out/'new_app_before_sync.zip').is_file())
        self.assertEqual((src/'entry.cpp').read_bytes(),(self.bundle/'app_src/entry.cpp').read_bytes())
    def test_existing_user_source_is_preserved(self):
        _,src=self.fixture();(src/'user.cpp').write_text('user work')
        with patch.object(platform,'assert_no_build_process'):
            with self.assertRaises(ValueError):platform.sync_sources(self.bundle,self.ws,self.manifest,{},self.out,True)
        self.assertEqual((src/'user.cpp').read_text(),'user work');self.assertFalse((src/'entry.cpp').exists())
    def test_readonly_platform_inspection_cannot_launch_xsct(self):
        self.ws.mkdir(parents=True);log=self.ws/'user.log';log.write_text('user-generated platform log')
        with patch.object(r,'inspect',return_value={}),patch.object(platform,'check_platform',return_value={'files':[]}),patch.object(platform.subprocess,'run',side_effect=AssertionError('no subprocess')):
            result=platform.inspect_user_platform(self.bundle,self.ws,self.out,log)
        self.assertEqual(result['result'],'USER_PLATFORM_READ_ONLY_PASS_NOT_SYNCED_OR_APP_BUILD')
        self.assertFalse((self.ws/r.APP_NAME).exists())

if __name__=='__main__':unittest.main()
