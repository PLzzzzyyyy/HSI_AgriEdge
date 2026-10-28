"""Pure real-wire uploader fixtures. No socket, model inference, or device writes."""
import copy
import hashlib
from pathlib import Path
import struct
import sys
import unittest
import zlib
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'gcs'))
import board_models as m
from board_upload import Transfer
from sim.host.test_gcs_models import fixture

def candidate(scene='honghu'):
    parts=fixture(scene)
    descriptors=[dict(kind=k,bytes=len(p),crc32=f'{zlib.crc32(p):08x}',sha256=hashlib.sha256(p).hexdigest()) for k,p in enumerate(parts)]
    return dict(scene=scene,tag='demo',version='v1',wcrc=descriptors[1]['crc32'],parts=descriptors),parts

class UploadTests(unittest.TestCase):
    def setup_transfer(self,action='upload',activate=False):
        c,parts=candidate();q=Transfer(7,42,action,c,parts,activate);sent=[]
        def send(kind,body,seq=None):
            seq=len(sent) if seq is None else seq;sent.append((kind,body,seq));return seq
        q.tick(0,send)
        self.assertEqual(sent[-1][0],7)
        q.received(dict(kind=0x86,boot_id=7,session=0,task=0,entries=[]))
        return q,sent,send

    def ack(self,q,code=0,value=0):
        o=q.outstanding;return q.received(dict(kind=0x83,task=q.task,acked_type=o['kind'],acked_seq=o['seq'],code=code,value=value))

    def test_full_upload_per_kind_persistence_info_then_activation(self):
        q,sent,send=self.setup_transfer(activate=True);step=1
        while not q.complete:
            q.tick(step*.001,send);step+=1;o=q.outstanding;kind=o['kind']
            if kind==m.WBEGIN:self.ack(q,value=0)
            elif kind==m.WCHUNK:self.ack(q,value=o['offset']+len(o['body'])-16)
            elif kind==m.WCOMMIT:
                self.assertIsNone(q.activated);self.ack(q,value=1)
            elif kind==7:
                self.assertTrue(all(q.persisted))
                entries=[dict(scene=1,kind=p['kind'],bytes=p['bytes'],wcrc=p['crc32'],tag='demo') for p in q.candidate['parts']]
                q.received(dict(kind=0x86,boot_id=7,session=42,task=0,entries=entries))
            else:self.assertEqual(kind,m.WACT);self.ack(q)
            self.assertLess(step,1000)
        s=q.snapshot();self.assertTrue(s['ok'] and s['registered'] and s['persisted'] and s['activated'])
        self.assertEqual(s['done'],s['total']);self.assertFalse(any(k in (1,9) for k,_,_ in sent))

    def test_partial_resume_retries_same_seq_and_bad_offsets_fail(self):
        q,sent,send=self.setup_transfer();q.tick(.01,send);q.tick(.4,send)
        self.assertEqual(sent[-1],sent[-2]);self.ack(q,value=1384)
        self.assertEqual(q.offset,1384);q.tick(.41,send);self.ack(q,2,0)
        self.assertEqual(q.offset,0);q.tick(.42,send)
        with self.assertRaisesRegex(ValueError,'mismatch'):self.ack(q,value=9999)

    def test_sd_error_deferred_commit_and_timeout_never_claim_active(self):
        q,sent,send=self.setup_transfer();q.tick(.01,send);self.ack(q,value=len(q.parts[0]));q.tick(.02,send)
        self.ack(q,value=0);self.assertFalse(q.complete);self.assertEqual(q.persisted,[False,None])
        n=len(sent);q.tick(500,send,idle=False);self.assertEqual(len(sent),n)
        q.tick(501,send,idle=True);self.ack(q,4,0)
        self.assertFalse(q.snapshot()['ok']);self.assertFalse(q.snapshot()['persisted']);self.assertIsNot(q.activated,True)
        q,sent,send=self.setup_transfer();q.tick(.01,send);q.tick(2,send)
        self.assertTrue(q.complete);self.assertFalse(q.snapshot()['ok']);self.assertIn('超时',q.error)

    def test_wrong_boot_missing_pair_and_mutated_local_bytes(self):
        c,parts=candidate();q=Transfer(7,42,'upload',c,parts);q.tick(0,lambda *a,**kw:3)
        with self.assertRaisesRegex(ValueError,'boot'):q.received(dict(kind=0x86,boot_id=8,session=42,task=0,entries=[]))
        q,sent,send=self.setup_transfer(action='activate');self.assertTrue(q.complete);self.assertFalse(q.snapshot()['ok'])
        c['parts'][1]['crc32']='12345678'
        with self.assertRaisesRegex(ValueError,'CRC|changed'):Transfer(7,42,'upload',c,parts)

    def test_activation_crc_must_identify_the_validated_engine_part(self):
        c,parts=candidate()
        mutations=[dict(c,wcrc='12345678'),dict(c,parts=list(reversed(c['parts'])))]
        for k,v in [('bytes',True),('kind',True),('sha256','not-a-sha'),('crc32','00000000')]:
            altered=copy.deepcopy(c);altered['parts'][1][k]=v;mutations.append(altered)
        for bad in mutations:
            with self.subTest(bad=bad),self.assertRaises(ValueError):Transfer(7,42,'activate',bad)
        # This API validates identity, not registration or hardware activation.
        self.assertEqual(m.candidate_identity(c)['wcrc'],c['parts'][1]['crc32'])

if __name__=='__main__':unittest.main()
