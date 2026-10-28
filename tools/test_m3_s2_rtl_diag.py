"""Negative controls for the n1 numeric oracle and exact-port RTL harness."""
from pathlib import Path
import struct
import tempfile
import unittest
import json
from unittest.mock import patch
import run_m3_s2_rtl_diag as diag
from run_m3_s2_rtl_diag import ROOT, GUARD, OUT_WORDS, MARKER, compare_output, make_top, execution_completed


class NewRtlSourceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.run=self.root/'build/host/m3_s2_synth_test'
        self.build=self.root/'build/hls/optimization_build/m3_s2_syn_8p1_pack_test'
        self.csim=self.root/'build/hls/optimization_build/m3_s2_8p1_pack_test'
        def put(path,text):path.parent.mkdir(parents=True,exist_ok=True);path.write_text(text)
        self.put=put
        put(self.run/'running.json',json.dumps(dict(finished=True)))
        put(self.run/'hls.log','synthesis completed')
        put(self.build/'synth.done','done');put(self.csim/'csim.done','done')
        put(self.build/'sol/syn/verilog/s2_engine.v','new DUT')
        self.source='src/hls/m3_s2/s2_engine.cpp'
        for base in (self.root,self.build/'snapshot',self.csim/'snapshot'):put(base/self.source,'new source')
        self.row=dict(name=self.build.name,source_csim=self.csim.name,num=8,p=1,pack=1,
            synthesis_completed=True,exit=0,timed_out=False,log=(self.run/'hls.log').relative_to(self.root).as_posix(),
            log_sha256=diag.sha(self.run/'hls.log'),snapshot={self.source:diag.sha(self.root/self.source)},
            continuation_blockers=['G2 FAIL retained'])
        self.save()
        self.root_patch=patch.object(diag,'ROOT',self.root);self.root_patch.start()

    def save(self):self.put(self.run/'results.json',json.dumps([self.row]))
    def tearDown(self):self.root_patch.stop();self.tmp.cleanup()

    def test_new_p1_not_old_dut_and_g2_not_relabeled(self):
        self.assertEqual(diag.validated_synth_rtl('test'),self.build/'sol/syn/verilog')
        self.assertEqual(json.loads((self.run/'results.json').read_text())[0]['continuation_blockers'],['G2 FAIL retained'])

    def test_reject_stale_source_or_csim(self):
        for path in (self.root/self.source,self.csim/'snapshot'/self.source):
            self.put(path,'stale')
            with self.assertRaisesRegex(RuntimeError,'source/CSim mismatch'):diag.validated_synth_rtl('test')
            self.put(path,'new source')

    def test_reject_wrong_configuration_or_failed_synthesis(self):
        for key,value in [('p',2),('synthesis_completed',False),('timed_out',True)]:
            original=self.row[key];self.row[key]=value;self.save()
            with self.assertRaises(RuntimeError):diag.validated_synth_rtl('test')
            self.row[key]=original

    def test_reject_missing_receipt_or_log_mutation(self):
        (self.csim/'csim.done').unlink()
        with self.assertRaises(RuntimeError):diag.validated_synth_rtl('test')
        self.put(self.csim/'csim.done','done');self.put(self.run/'hls.log','changed')
        with self.assertRaisesRegex(RuntimeError,'log mismatch'):diag.validated_synth_rtl('test')

    def test_bind_observation_to_new_instance_numbers(self):
        rtl='s2_engine_core_send_weights grp_core_send_weights_fu_9 (\n);\ns2_engine_load grp_load_fu_17 (\n);'
        text=diag.load_observation(rtl)
        self.assertIn('grp_core_send_weights_fu_9_ap_done',text)
        self.assertIn('grp_load_fu_17_ap_done',text)
        with self.assertRaises(RuntimeError):diag.load_observation('unknown RTL hierarchy')

    def test_observation_net_is_not_a_submodule_port_name(self):
        top='wire [191:0] engine_task_U0_cq_din;\ns2_engine_engine_task engine_task_U0 (\n.cq_din(engine_task_U0_cq_din));'
        diag.validate_observation_nets(top,'dut.engine_task_U0_cq_din dut.engine_task_U0.ap_CS_fsm')
        with self.assertRaisesRegex(RuntimeError,'Unknown DUT observation'):
            diag.validate_observation_nets(top,'dut.cq_din')

    def test_fp_config_and_model_hash_must_match(self):
        rtl=self.build/'sol/syn/verilog';ooc=self.root/'models'
        inputs={};hashes={}
        for i in range(5):
            self.put(rtl/f'fp{i}_ip.tcl',f'config{i}');inputs[f'rtl/fp{i}_ip.tcl']=diag.sha(rtl/f'fp{i}_ip.tcl')
            model=ooc/f'project/s2_ooc.gen/sources_1/ip/fp{i}/sim/fp{i}.v'
            self.put(model,f'model{i}');hashes[f'rtl/fp{i}.v']=diag.sha(model)
        self.put(ooc/'results.json',json.dumps(dict(inputs=inputs)))
        self.put(self.root/'build/host/m3_s2_rtl_20261008_r9_n1_direct_r4/inputs.json',json.dumps(dict(files=hashes)))
        self.assertEqual(len(diag.validated_fp_models(rtl,ooc)),5)
        self.put(rtl/'fp0_ip.tcl','changed')
        with self.assertRaisesRegex(RuntimeError,'configuration changed'):diag.validated_fp_models(rtl,ooc)
        self.put(rtl/'fp0_ip.tcl','config0');self.put(model,'changed')
        with self.assertRaisesRegex(RuntimeError,'model hash mismatch'):diag.validated_fp_models(rtl,ooc)


class ExecutionReceiptTests(unittest.TestCase):
    def test_exit_zero_watchdog_or_interruption_is_not_pass(self):
        for text in ['Fatal: LOAD_NO_PROGRESS','Simulation engine not responding',
                     MARKER+' cannot be opened for reading',MARKER+' ERROR:',
                     MARKER+' Fatal: failed']:
            self.assertFalse(execution_completed(dict(exit=0,timed_out=False),text))

    def test_marker_requires_success_and_no_timeout(self):
        self.assertTrue(execution_completed(dict(exit=0,timed_out=False),MARKER))
        self.assertFalse(execution_completed(dict(exit=1,timed_out=False),MARKER))
        self.assertFalse(execution_completed(dict(exit=0,timed_out=True),MARKER))


class NumericOracleTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.out=Path(self.tmp.name)
        self.golden=ROOT/'sim/golden/n6_engine_i8/a'
        self.image=bytearray(struct.pack('<Q',GUARD)*OUT_WORDS)
        for name,offset in [('logits_q16_i32.bin',0),('class_u32.bin',0x100)]+[(f'L{i}_x_out_i4.bin',0x1000+i*7938*8) for i in range(12)]:
            data=(self.golden/name).read_bytes();self.image[offset:offset+len(data)]=data

    def tearDown(self):self.tmp.cleanup()

    def write(self):
        (self.out/'output.hex').write_text(''.join(f'{w[0]:016x}\n' for w in struct.iter_unpack('<Q',self.image)))

    def test_complete_golden_and_all_guards(self):
        self.write();r=compare_output(self.out,self.golden)
        self.assertTrue(r['passed']);self.assertEqual(len(r['spans']),14)

    def test_partial_layer_snapshots_never_imply_complete_n1(self):
        data=(self.golden/'L0_x_out_i4.bin').read_bytes()
        p=self.out/'layer_00.hex'
        p.write_text(''.join(f'{w[0]:016x}\n' for w in struct.iter_unpack('<Q',data)))
        r=diag.compare_layer_snapshots(self.out,self.golden)
        self.assertTrue(r['layers'][0]['match']);self.assertFalse(r['all_12_match'])
        bad=bytearray(data);bad[8]^=1
        p.write_text(''.join(f'{w[0]:016x}\n' for w in struct.iter_unpack('<Q',bad)))
        self.assertFalse(diag.compare_layer_snapshots(self.out,self.golden)['layers'][0]['match'])
        p.write_text('xxxx\n')
        with self.assertRaises(ValueError):diag.compare_layer_snapshots(self.out,self.golden)
        p.write_text('1234\n')
        with self.assertRaises(RuntimeError):diag.compare_layer_snapshots(self.out,self.golden)

    def test_layer11_bit_flip(self):
        self.image[0x1000+11*7938*8+900]^=1;self.write()
        r=compare_output(self.out,self.golden);self.assertFalse(r['passed'])
        self.assertFalse(r['spans'][-1]['match'])

    def test_unwritten_gap_and_class_upper_half_guard(self):
        for offset in [0x104,0x200,len(self.image)-1]:
            self.image[offset]^=1;self.write()
            self.assertFalse(compare_output(self.out,self.golden)['passed']);self.image[offset]^=1

    def test_truncation_and_unknown_fail_closed(self):
        (self.out/'output.hex').write_text('x\n')
        with self.assertRaises(ValueError):compare_output(self.out,self.golden)
        (self.out/'output.hex').write_text('0\n')
        with self.assertRaises(RuntimeError):compare_output(self.out,self.golden)

    def test_exact_ports_and_three_distinct_memories(self):
        rtl=(ROOT/'build/host/m3_s2_ooc_20261008_t3_fix_r9_ip/rtl/s2_engine.v').read_text()
        top=make_top(rtl,42008)
        self.assertIn('.s_axi_control_AWADDR(s_axi_control_AWADDR)',top)
        self.assertEqual(top.count('s2_axi_memory #'),3)
        self.assertIn('.WORDS(95772)',top)


if __name__=='__main__':unittest.main()
