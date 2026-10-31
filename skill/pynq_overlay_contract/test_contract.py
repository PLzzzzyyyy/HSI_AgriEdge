"""Synthetic regression: metadata compatibility, real CLI, and no-download contract."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from inspect_overlay import check,inspect

HERE=Path(__file__).resolve().parent

class ContractTests(unittest.TestCase):
    def setUp(self):
        self.contract=json.loads((HERE/'examples/accelerator_contract.json').read_text('utf-8'))
        self.metadata=json.loads((HERE/'examples/accelerator_ip_dict.json').read_text('utf-8'))

    def test_two_unrelated_designs_and_relocated_addresses(self):
        check(self.contract,self.metadata)
        self.metadata['accelerator_0']['phys_addr']=0xa0010000
        check(self.contract,self.metadata)
        check(json.loads((HERE/'examples/gpio_contract.json').read_text('utf-8')),
              json.loads((HERE/'examples/gpio_ip_dict.json').read_text('utf-8')))

    def test_missing_ip(self):
        with self.assertRaisesRegex(ValueError,'Missing IP'):check(self.contract,{})

    def test_wrong_ip_version(self):
        self.metadata['accelerator_0']['type']='example.org:user:vector_add:2.0'
        with self.assertRaisesRegex(ValueError,'VLNV'):check(self.contract,self.metadata)

    def test_short_unaligned_or_invalid_range(self):
        for key,value in [('addr_range',128),('phys_addr',3),('addr_range',True),('addr_range',4095.5)]:
            with self.subTest(key=key,value=value):
                data=copy.deepcopy(self.metadata);data['accelerator_0'][key]=value
                with self.assertRaises(ValueError):check(self.contract,data)

    def test_parameter_mismatch(self):
        self.metadata['accelerator_0']['parameters']['C_DATA_WIDTH']='64'
        with self.assertRaisesRegex(ValueError,'Parameter'):check(self.contract,self.metadata)

    def test_pynq_adapter_never_downloads(self):
        calls=[];metadata=self.metadata
        class OverlayDouble:
            def __init__(self,path,download=True):
                calls.append(download)
                if download:raise AssertionError('Unexpected download')
                self.ip_dict=metadata
            def download(self):raise AssertionError('Unexpected download')
        with tempfile.TemporaryDirectory() as temp:
            bit=Path(temp)/'generic.bit';hwh=bit.with_suffix('.hwh')
            bit.write_bytes(b'synthetic-not-a-bitstream');hwh.write_text('<synthetic/>')
            contract=copy.deepcopy(self.contract)
            contract['assets']={'bit_sha256':hashlib.sha256(bit.read_bytes()).hexdigest(),
                                'hwh_sha256':hashlib.sha256(hwh.read_bytes()).hexdigest()}
            result=inspect(contract,bitfile=bit,overlay_class=OverlayDouble)
            self.assertEqual(result['result'],'PASS');self.assertEqual(calls,[False])
            hwh.write_text('<changed/>')
            with self.assertRaisesRegex(ValueError,'SHA256'):inspect(contract,bitfile=bit,overlay_class=OverlayDouble)
            self.assertEqual(calls,[False])

    def test_cli_positive_and_negative_exit_status(self):
        positive=subprocess.run([sys.executable,str(HERE/'inspect_overlay.py'),'--contract',
            str(HERE/'examples/accelerator_contract.json'),'--ip-dict',str(HERE/'examples/accelerator_ip_dict.json')],capture_output=True,text=True)
        self.assertEqual(positive.returncode,0);self.assertEqual(json.loads(positive.stdout)['result'],'PASS')
        negative=subprocess.run([sys.executable,str(HERE/'inspect_overlay.py'),'--contract',
            str(HERE/'examples/accelerator_contract.json'),'--ip-dict',str(HERE/'examples/gpio_ip_dict.json')],capture_output=True,text=True)
        self.assertEqual(negative.returncode,1);self.assertEqual(json.loads(negative.stdout)['result'],'FAIL')

if __name__=='__main__':unittest.main(verbosity=2)
