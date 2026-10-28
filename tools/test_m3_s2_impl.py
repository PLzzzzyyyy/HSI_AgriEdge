"""Small, tool-free regression tests for the diagnostic checkpoint provenance gate."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import run_m3_s2_impl as impl


class ProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.mock_root = patch.object(impl, 'ROOT', self.root)
        self.mock_root.start()
        self.addCleanup(self.mock_root.stop)
        self.ooc = self.root / 'ooc'
        self.build = self.root / 'build/hls/optimization_build/m3_s2_syn_8p1_pack_test'
        self.synth = self.root / 'build/host/m3_s2_synth_test'
        self.write(self.ooc / 'rtl/top.v', 'module s2_engine; endmodule\n')
        self.write(self.build / 'sol/syn/verilog/top.v', 'module s2_engine; endmodule\n')
        self.write(self.root / 'src/hls/test.cpp', 'int value;\n')
        self.write(self.build / 'snapshot/src/hls/test.cpp', 'int value;\n')
        # Generated snapshot metadata is not a file under the repository root.
        self.write(self.build / 'snapshot/input_csim.done', 'COMPLETE\n')
        self.write(self.build / 'synth.done', 'COMPLETE\n')
        self.write(self.root / 'hls.log', 'HLS completed\n')
        with zipfile.ZipFile(self.ooc / 's2_engine_ooc.dcp', 'w') as archive:
            archive.writestr('dcp.xml', '<Checkpoint><Top Name="s2_engine"/>'
                '<Part Name="xazu5ev-sfvc784-1-i"/><OutOfContext Name="1"/></Checkpoint>')
        impl.dump(self.ooc / 'running.json', dict(finished=True))
        self.write(self.ooc / 'mapping.done', 'COMPLETE\n')
        self.receipt = dict(finished=True, mapping_completed=True, exit=0,
            timed_out=False, part='xazu5ev-sfvc784-1-i', clock_ns=5.0, synth_tag='test',
            inputs={'rtl/top.v': impl.sha(self.ooc / 'rtl/top.v')},
            artifacts={'s2_engine_ooc.dcp': impl.sha(self.ooc / 's2_engine_ooc.dcp')})
        impl.dump(self.ooc / 'results.json', self.receipt)
        self.synth.mkdir(parents=True)
        impl.dump(self.synth / 'running.json', dict(finished=True))
        self.row = dict(name=self.build.name, synthesis_completed=True,
            log='hls.log', log_sha256=impl.sha(self.root / 'hls.log'),
            snapshot={n: impl.sha(self.build / 'snapshot' / n) for n in
                      ('src/hls/test.cpp', 'input_csim.done')})
        impl.dump(self.synth / 'results.json', [self.row])

    @staticmethod
    def write(path, text):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def reject(self, message):
        with self.assertRaisesRegex(RuntimeError, message):
            impl.validate_ooc(self.ooc)

    def test_valid_including_generated_metadata(self):
        self.assertEqual(impl.validate_ooc(self.ooc), self.receipt)

    def test_unfinished_ooc(self):
        impl.dump(self.ooc / 'running.json', dict(finished=False))
        self.reject('not completed')

    def test_nonzero_exit_despite_completed_flag(self):
        self.receipt['exit'] = 1
        impl.dump(self.ooc / 'results.json', self.receipt)
        self.reject('not completed')

    def test_clock_mismatch(self):
        self.receipt['clock_ns'] = 10
        impl.dump(self.ooc / 'results.json', self.receipt)
        self.reject('part or clock')

    def test_dcp_tampering(self):
        self.write(self.ooc / 's2_engine_ooc.dcp', 'corrupt')
        self.reject('hash mismatch')

    def test_wrong_top_even_with_matching_hash(self):
        with zipfile.ZipFile(self.ooc / 's2_engine_ooc.dcp', 'w') as archive:
            archive.writestr('dcp.xml', '<Checkpoint><Top Name="wrong"/>'
                '<Part Name="xazu5ev-sfvc784-1-i"/><OutOfContext Name="1"/></Checkpoint>')
        self.receipt['artifacts']['s2_engine_ooc.dcp'] = impl.sha(self.ooc / 's2_engine_ooc.dcp')
        impl.dump(self.ooc / 'results.json', self.receipt)
        self.reject('metadata mismatch')

    def test_current_source_change(self):
        self.write(self.root / 'src/hls/test.cpp', 'int changed;')
        self.reject('Current source mismatch')

    def test_hls_snapshot_change(self):
        self.write(self.build / 'snapshot/src/hls/test.cpp', 'int changed;')
        self.reject('HLS snapshot mismatch')

    def test_hls_rtl_change(self):
        self.write(self.build / 'sol/syn/verilog/top.v', 'module wrong; endmodule')
        self.reject('HLS/OOC RTL mismatch')

    def test_hls_log_change(self):
        self.write(self.root / 'hls.log', 'changed')
        self.reject('HLS log hash mismatch')

    def test_non_p1(self):
        self.row['name'] = 'm3_s2_syn_8p2_pack_test'
        impl.dump(self.synth / 'results.json', [self.row])
        self.reject('P1 W8 only')


if __name__ == '__main__':
    unittest.main(verbosity=2)
