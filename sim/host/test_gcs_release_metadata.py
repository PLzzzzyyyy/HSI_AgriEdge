"""Vitis post-Build metadata and current DP gates; no devices or App Build."""
from pathlib import Path
import sys, unittest
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
import gcs_release_elf as elf

BEFORE=b'''<?xml version="1.0" encoding="ASCII"?>
<SdkProject xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" platform="new.xpfm" cpu="standalone_domain" mssSignature="unchanged">
  <configuration name="Debug" id="xilinx.gnu.arm.a53.exe.debug.123" dirty="true">
    <configBuildOptions xsi:type="sdkproject:SdkOptions"/>
  </configuration>
  <configuration name="Release" id="xilinx.gnu.arm.a53.exe.release.456" dirty="true">
    <configBuildOptions xsi:type="sdkproject:SdkOptions"/>
  </configuration>
</SdkProject>
'''
AFTER=BEFORE.replace(b' id="xilinx.gnu.arm.a53.exe.debug.123" dirty="true"',b' id="xilinx.gnu.arm.a53.exe.debug.123"').replace(
    b'    <configBuildOptions xsi:type="sdkproject:SdkOptions"/>\n',
    b'    <configBuildOptions xsi:type="sdkproject:SdkOptions"/>\n    <lastBuildOptions xsi:type="sdkproject:SdkOptions"/>\n',1)

class Metadata(unittest.TestCase):
    def assert_rejected(self,data):
        try:normalized=elf.normalized_prj(data)
        except ValueError:return
        self.assertNotEqual(normalized,elf.normalized_prj(BEFORE))
    def test_real_empty_debug_bookkeeping_is_not_config_change(self):
        for newline in (b'\n',b'\r\n'):
            with self.subTest(newline=newline):
                self.assertEqual(elf.normalized_prj(BEFORE.replace(b'\n',newline)),elf.normalized_prj(AFTER.replace(b'\n',newline)))
    def test_debug_dirty_boolean_remains_supported(self):
        for state in (b'false',b'true'):
            self.assertEqual(elf.normalized_prj(BEFORE),elf.normalized_prj(AFTER.replace(b' id="xilinx.gnu.arm.a53.exe.debug.123"',b' id="xilinx.gnu.arm.a53.exe.debug.123" dirty="'+state+b'"')))
    def test_nonempty_last_build_options_are_not_ignored(self):
        for payload in (b'<lastBuildOptions xsi:type="sdkproject:SdkOptions" flags="-Ofast"/>',
                        b'<lastBuildOptions xsi:type="sdkproject:SdkOptions"><flag value="bad"/></lastBuildOptions>',
                        b'<lastBuildOptions xsi:type="sdkproject:SdkOptions">changed</lastBuildOptions>',
                        b'<lastBuildOptions xsi:type="other:Options"/>'):
            self.assert_rejected(AFTER.replace(b'<lastBuildOptions xsi:type="sdkproject:SdkOptions"/>',payload))
    def test_duplicate_bookkeeping_is_rejected(self):
        line=b'    <lastBuildOptions xsi:type="sdkproject:SdkOptions"/>\n'
        self.assert_rejected(AFTER.replace(line,line+line))
    def test_release_metadata_is_not_ignored(self):
        self.assert_rejected(AFTER.replace(b' id="xilinx.gnu.arm.a53.exe.release.456" dirty="true"',b' id="xilinx.gnu.arm.a53.exe.release.456" dirty="false"'))
        self.assert_rejected(AFTER.replace(b'</SdkProject>',b'<lastBuildOptions xsi:type="sdkproject:SdkOptions"/></SdkProject>'))
    def test_target_signature_and_real_config_still_protected(self):
        for before,after in ((b'new.xpfm',b'old.xpfm'),(b'standalone_domain',b'fsbl'),
                             (b'mssSignature="unchanged"',b'mssSignature="changed"'),
                             (b'<configBuildOptions xsi:type="sdkproject:SdkOptions"/>',b'<configBuildOptions xsi:type="sdkproject:SdkOptions" flags="-Ofast"/>')):
            self.assert_rejected(AFTER.replace(before,after,1))
    def test_duplicate_debug_scope_is_rejected(self):
        extra=b'<configuration name="Debug" id="duplicate"><lastBuildOptions xsi:type="sdkproject:SdkOptions"/></configuration>'
        self.assert_rejected(AFTER.replace(b'</SdkProject>',extra+b'</SdkProject>'))

CURRENT_FEATURES=(
    'gcs_release_identity','tt_m3a_run(','tt_m3a_load_weights(','tt_m3a_set_wait_service(',
    's2c::acquire_sd_boot_id(','s2c::step_task(','s2c::probe_model(',
    's2c::display_init(','s2c::display_scene_begin(','s2c::display_scene_append(','s2c::display_scene_update(',
    'XDpPsu_CfgInitialize','XDpDma_DisplayGfxFrameBuffer',
    's2c::Models::activate(','s2c::ModelSd::scan(','XTt_engine_Get_cycles')

class DisplayFeatures(unittest.TestCase):
    @staticmethod
    def rows(names):return [dict(name=n,address=0x1000+i*64,size=32) for i,n in enumerate(names)]
    def test_current_full_scene_dp_path_passes_without_unused_legacy_symbol(self):
        self.assertTrue(elf.audit_feature_symbols(self.rows(CURRENT_FEATURES)))
    def test_each_required_current_feature_is_enforced(self):
        for missing in CURRENT_FEATURES:
            with self.subTest(missing=missing),self.assertRaises(ValueError):
                elf.audit_feature_symbols(self.rows([n for n in CURRENT_FEATURES if n!=missing]))
    def test_legacy_display_update_does_not_replace_full_scene_path(self):
        names=[n for n in CURRENT_FEATURES if not n.startswith('s2c::display_scene_')]+['s2c::display_update(']
        with self.assertRaises(ValueError):elf.audit_feature_symbols(self.rows(names))

if __name__=='__main__':unittest.main()
