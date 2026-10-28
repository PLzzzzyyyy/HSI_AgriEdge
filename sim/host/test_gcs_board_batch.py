"""Copy/backup gates in an isolated temporary tree, never the user's Vitis App."""
from pathlib import Path
import json
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'tools'))
import gcs_board_batch as b

class BatchTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.root_patch=patch.object(b,'ROOT',self.root);self.root_patch.start()
        self.process_patch=patch.object(b,'assert_no_build_process');self.process=self.process_patch.start()
        self.archive=self.root/b.BASE_ARCHIVE;self.archive.parent.mkdir(parents=True)
        with zipfile.ZipFile(self.archive,'w') as z:
            for relative in b.SOURCES:
                name=Path(relative).name;old=('old '+name).encode()
                source=self.root/relative;source.parent.mkdir(parents=True,exist_ok=True)
                source.write_bytes(('new '+name).encode() if name in b.ALLOWED else old)
                dest=self.root/b.APP/'src'/name;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(old)
                z.writestr(dest.relative_to(self.root).as_posix(),old)
            for name in b.PROTECTED:
                p=self.root/b.APP/name;p.write_bytes(b'protected')
                if not name.endswith('.prj'):z.writestr(p.relative_to(self.root).as_posix(),b'protected')
        (self.root/b.BASE_CONFIG).write_text(json.dumps(dict(after={(b.APP/n).as_posix():b.digest(b'protected') for n in b.PROTECTED})))
        elf=self.root/b.APP/'Debug/s2c_roi_app.elf';elf.parent.mkdir();elf.write_bytes(b'old elf')
        self.bundle=self.root/'build/host/test_bundle'
    def tearDown(self):
        self.process_patch.stop();self.root_patch.stop();self.temp.cleanup()
    def test_prepare_no_app_mutation_and_syntax_not_automatically_run(self):
        m=b.prepare(self.bundle);self.assertEqual(len(m['files']),24);self.assertEqual(set(m['changed']),b.ALLOWED)
        self.assertEqual((self.root/b.APP/'src/main.cpp').read_bytes(),b'old main.cpp')
        self.assertEqual((self.root/b.APP/'Debug/s2c_roi_app.elf').read_bytes(),b'old elf')
    def test_explicit_confirmation_before_any_write(self):
        b.prepare(self.bundle)
        with self.assertRaisesRegex(ValueError,'confirm'):b.sync(self.bundle)
        self.process.assert_not_called()
        self.assertFalse((self.root/'report/gcs_roi/20261010_s3').exists())
    def test_source_config_drift_and_new_compile_unit_rejected(self):
        b.prepare(self.bundle)
        for path in (self.root/b.APP/'src/main.cpp',self.root/b.APP/'.cproject',self.bundle/'app_src/main.cpp'):
            original=path.read_bytes();path.write_bytes(b'changed elsewhere')
            with self.assertRaises(ValueError):b.sync(self.bundle,True)
            path.write_bytes(original)
        (self.root/b.APP/'src/other.cpp').write_bytes(b'user unrelated code')
        with self.assertRaises(ValueError):b.sync(self.bundle,True)
    def test_build_active_rejected_without_sync(self):
        b.prepare(self.bundle);self.process.side_effect=ValueError('Build active')
        with self.assertRaisesRegex(ValueError,'Build active'):b.sync(self.bundle,True)
        self.assertEqual((self.root/b.APP/'src/main.cpp').read_bytes(),b'old main.cpp')
    def test_post_sync_debug_dirty_marker_only_is_not_config_drift(self):
        path=self.root/b.APP/'s2c_roi_app.prj'
        base=b'<project><configuration name="Debug" id="123"><options/></configuration></project>'
        path.write_bytes(base)
        receipt=json.loads((self.root/b.BASE_CONFIG).read_text())
        receipt['after'][(b.APP/'s2c_roi_app.prj').as_posix()]=b.digest(base)
        (self.root/b.BASE_CONFIG).write_text(json.dumps(receipt))
        b.prepare(self.bundle);b.sync(self.bundle,True)
        for value in (b'true',b'false'):
            marked=base.replace(b'id="123"',b'id="123" dirty="'+value+b'"')
            path.write_bytes(marked);b.inspect(self.bundle,after_sync=True)
            self.assertEqual(path.read_bytes(),marked) # read-only, never erase IDE state
        for bad in (marked.replace(b'id="123"',b'id="456"'),marked.replace(b'<options/>',b'<changed/>'),
                    base.replace(b'id="123"',b'id="123" dirty="maybe"')):
            path.write_bytes(bad)
            with self.assertRaises(ValueError):b.inspect(self.bundle,after_sync=True)
    def test_sync_backs_up_exact_before_preserves_config_and_old_elf(self):
        m=b.prepare(self.bundle);r=b.sync(self.bundle,True)
        self.assertEqual(r['result'],'SYNC_ONLY_PASS_NOT_BUILT');self.assertEqual(set(r['copied']),b.ALLOWED)
        b.inspect(self.bundle,after_sync=True)
        with zipfile.ZipFile(r['backup']) as z:
            self.assertEqual(z.read((b.APP/'src/main.cpp').as_posix()),b'old main.cpp')
        for name in b.PROTECTED:self.assertEqual((self.root/b.APP/name).read_bytes(),b'protected')
        with self.assertRaisesRegex(ValueError,'OLD build'):b.audit(self.bundle)
        with self.assertRaises(ValueError):b.sync(self.bundle,True) # no silent overwrite/replay

if __name__=='__main__':unittest.main(verbosity=2)
