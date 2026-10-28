"""OFFLINE model-package contracts. No inference, sockets or device writes."""
import hashlib
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
import zlib

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'gcs'))
import board_models as M


def fixture(scene='longkou'):
    n = M.scene_spec(scene)['classes']
    companion = bytes(363432+n*10588)
    engine = bytearray(M.ENGINE_BYTES)
    struct.pack_into('<4I', engine, 0, 0x32455454, 2, n, 16)
    return companion, bytes(engine)


class ModelContracts(unittest.TestCase):
    def test_scene_dimensions_and_preprocessing_are_explicit(self):
        self.assertEqual(M.scene_spec('honghu')['shape'], [940, 475])
        self.assertEqual(M.scene_spec(2)['classes'], 16)
        self.assertEqual(M.scene_spec('hanchuan')['band_drop'], [270,271,272,273])
        with self.assertRaises(ValueError):M.scene_spec(True)
        with self.assertRaises(ValueError):M.scene_spec('unknown')

    def test_each_scene_checks_pair_not_merely_tte2_header(self):
        for scene in M.SCENES:
            a,b=fixture(scene)
            M.validate_package(scene, 0, a)
            M.validate_package(scene, 1, b)
            M.validate_pair(scene,a,b)
            bad=bytearray(b);bad[-1]=1
            with self.assertRaisesRegex(ValueError,'projection'):M.validate_pair(scene,a,bad)
            bad=bytearray(b);struct.pack_into('<I',bad,8,1)
            with self.assertRaises(ValueError):M.validate_package(scene,1,bad)

    def test_rejects_bad_shape_width_reserved_padding_nan_and_paths(self):
        a,b=fixture()
        for off,value in ((0,0),(4,1),(12,8),(16,1),(56,1),(63616+9*4,1),(63744+5292,1)):
            bad=bytearray(b);struct.pack_into('<I',bad,off,value)
            with self.assertRaises(ValueError):M.validate_package('longkou',1,bad)
        for content in (b[:-1], b+b'\0'):
            with self.assertRaises(ValueError):M.validate_package('longkou',1,content)
        bad=bytearray(a);struct.pack_into('<f',bad,289344,float('nan'))
        with self.assertRaises(ValueError):M.validate_package('longkou',0,bad)
        for tag in ('', '../v1', 'a/b', 'a\\b', 'v.1', 'x'*16, '版本', 'ok\0bad'):
            with self.assertRaises(ValueError):M.valid_tag(tag)
        self.assertEqual(M.valid_tag('live1011_123456'), 'live1011_123456')

    def test_pair_embedding_mismatch_rejected(self):
        a,b=fixture();bad=bytearray(a)
        struct.pack_into('<f',bad,289344,0.5)
        with self.assertRaisesRegex(ValueError,'embedding'):M.validate_pair('longkou',bad,b)

    def test_local_package_never_means_present_or_activated_on_board(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);d=root/'longkou/weights/demo';d.mkdir(parents=True)
            a,b=fixture();off=0;hashes={}
            for name,size in M.part_files('longkou'):
                raw=a[off:off+size];off+=size;(d/name).write_bytes(raw)
                hashes[name]=hashlib.sha256(raw).hexdigest()
            (d/'weights_engine.bin').write_bytes(b);hashes['weights_engine.bin']=hashlib.sha256(b).hexdigest()
            manifest=dict(schema=1,scene='longkou',tag='demo',checkpoint_sha256='a'*64,files=hashes)
            (d/'board_model.json').write_text(json.dumps(manifest))
            candidate=M.load_candidate(root,'longkou','demo')
            self.assertEqual(candidate['wcrc'],f'{zlib.crc32(b):08x}')
            self.assertFalse(candidate['board_registered'])
            self.assertIsNone(candidate['board_persisted'])
            self.assertIsNone(candidate['board_activated'])
            self.assertEqual(len(M.package_parts(root,'longkou','demo')),2)
            changed=bytearray(b);changed[-1]=3;(d/'weights_engine.bin').write_bytes(changed)
            with self.assertRaisesRegex(ValueError,'SHA256'):M.load_candidate(root,'longkou','demo')

    def test_info_entries_match_both_packages_and_reject_crc_alias(self):
        a,b=fixture();candidate=dict(scene='longkou',tag='demo',parts=[
            dict(kind=k,bytes=len(p),crc32=f'{zlib.crc32(p):08x}') for k,p in enumerate((a,b))])
        entries=[dict(scene=0,kind=p['kind'],bytes=p['bytes'],wcrc=p['crc32'],tag='demo') for p in candidate['parts']]
        self.assertTrue(M.registered(candidate,entries))
        self.assertFalse(M.registered(candidate,entries[:1]))
        self.assertFalse(M.registered(candidate,[dict(e,tag='other') for e in entries]))
        self.assertFalse(M.registered(candidate,entries+[dict(entries[1],tag='alias')]))


if __name__=='__main__':unittest.main()
