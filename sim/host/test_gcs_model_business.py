"""Model-aware task evidence/statistics on synthetic words, never board results."""
import csv
import io
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
import zlib
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'gcs'),str(ROOT/'tools')]
import board_models as m
import board_task as t
import board_metrics
import board_agri
import board_history
import gcs_task_verify as verify
from sim.host.test_gcs_model_transport import descriptor,status
w=t.wire

def fixture(root,scene):
    spec=m.scene_spec(scene);h,width=spec['shape'];y,x=h-1,width-1;ncls=spec['classes'];word=0xffff0000|ncls-1
    j=t.Job(0x12345678,42,7,[y,x,1,1],False,identity=descriptor(scene));j.out=root/'task';j.out.mkdir()
    j.host_run=dict(id=1,kind='region',scene=scene,version='demo',rect=[y,x,1,1],t0=1.)
    t.save_json(j.out/'session.json',dict(boot_id=j.audit.boot,session=42,task=7,identity=j.audit.identity,rect=[y,x,1,1],
        fresh=False,host_run=j.host_run,target=w.TARGET,scope='MODEL_TASK_LIFECYCLE'))
    packets=[('tx',w.packet(1,7,1,1,j.audit.start_body())),('rx',w.packet(0x83,7,2,2,struct.pack('<BBHI',1,0,1,0))),
        ('rx',w.packet(0x81,7,3,3,struct.pack('<4HI',y,x,1,0,word)))]
    final=bytearray(status(scene=scene,rect=(y,x,1,1)));struct.pack_into('<f',final,20,5.0);packets.append(('rx',bytes(final)))
    with (j.out/'packets.jsonl').open('w',encoding='utf-8') as f:
        for direction,raw in packets:
            f.write(json.dumps(dict(direction=direction,peer=w.TARGET,hex=raw.hex()))+'\n')
            if direction=='tx':j.audit.sent(raw)
            else:j.audit.received(raw)
    j.last_status=j.audit.last_status;j.state='done';t.save_json(j.out/'summary.json',j.snapshot())
    crc=zlib.crc32(struct.pack('<I',word));uart=root/'uart.txt'
    uart.write_text(f'S2C READY boot_id=12345678 registry=6 scan_ok=1 scenes=3 roi=any banks=1 UDP=5010 app=model_lifecycle_r1\n'
        f'S2C TASK_BEGIN session=0000002a task=7 scene={spec["id"]} model=demo wcrc=12345678 x={x} y={y} w=1 h=1 classes={ncls}\n'
        f'S2C S3 scope=task session=0000002a task=7 wait_calls=10 wait_rx=1 max_gap_us=100 max_service_us=5\n'
        f'S2C TASK_DONE session=0000002a task=7 completed=1 compute_us=5000 crc32={crc:08x}\n',encoding='utf-8')
    return j,uart

class ModelBusinessTests(unittest.TestCase):
    def test_three_scene_independent_uart_packet_export_and_label_contracts(self):
        for scene in m.SCENES:
            with self.subTest(scene=scene),tempfile.TemporaryDirectory() as tmp:
                j,uart=fixture(Path(tmp),scene);r=verify.verify(j.out,uart)
                self.assertTrue(r['data_acceptance']);self.assertFalse(r['batch_acceptance'])
                self.assertEqual(r['identity'],j.audit.identity);self.assertEqual(len(r['browser_words_sha256']),64)
                restored=board_history.load_job(j.out);self.assertEqual(restored.audit.identity,j.audit.identity);self.assertFalse(restored.integrity_error)
                metrics=board_metrics.from_snapshot(j.snapshot())
                self.assertEqual(metrics['identity']['model'],'demo');self.assertEqual(metrics['evaluation']['scene'],scene)
                self.assertFalse(metrics['complete_test_coverage']);self.assertEqual(metrics['received_pixels'],1)
                spec=m.scene_spec(scene);names=metrics['evaluation']['classes']
                result=board_agri.BoardResult(j.snapshot(),spec['shape'],names)
                self.assertEqual(result.identity['wcrc'],'12345678');self.assertEqual(result.count,1)
                rows=list(csv.DictReader(io.StringIO(t.csv_text(j.snapshot()))));self.assertEqual(rows[0]['scene'],scene)
                self.assertEqual(rows[0]['wcrc'],'12345678');self.assertEqual(int(rows[0]['classes']),spec['classes'])
                # Existing shape/label positions cannot masquerade as another model/scene.
                text=uart.read_text();uart.write_text(text.replace('wcrc=12345678','wcrc=12345679'))
                with self.assertRaises(ValueError):verify.verify(j.out,uart)

    def test_scene_specific_labels_and_snapshot_shape_do_not_follow_ui_choice(self):
        for scene in m.SCENES:
            labels,meta=board_metrics.load_label_set(scene=scene);spec=m.scene_spec(scene)
            self.assertEqual(list(labels['test'].shape),spec['shape']);self.assertEqual(meta['train_counts'],[100]*spec['classes'])
        with tempfile.TemporaryDirectory() as tmp:
            j,_=fixture(Path(tmp),'honghu');s=j.snapshot();s['shape']=[550,400]
            with self.assertRaises(ValueError):board_metrics.from_snapshot(s)
            with self.assertRaises(ValueError):board_agri.BoardResult(s,[550,400],['crop']*9)

if __name__=='__main__':unittest.main()
