"""Opt-in RX-only UART0 capture for SD-journal startup, no device reset or TX.

Import/status/port listing do not open a serial port or obtain random identity.
The operator connects BEFORE an independent cold start and retains all device
operations. The serial transcript cannot prove the physical cold-start action.
"""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import secrets
import threading
import time
from board_release import APP_ID,LEGACY_APP_ID,uart_build,expected_build

PROMPT = b'S2B BOOT_ID: 8 hex digits + LF/CRLF'
CAPTURE_SECONDS = 6*3600  # multi-scene/task capture bound, not measured runtime
MAX_BYTES = 16 * 1024 * 1024


class Identity:
    """Historical r1 parser retained for offline regression; NOT used by Capture."""
    def __init__(self, clock, value_factory, claim):
        self.state, self.error, self.boot = 'waiting_prompt', None, None
        self.buffer = b''
        self.deadline = clock + 180
        self.value_factory, self.claim = value_factory, claim
        self.ready_notified = False
        self.registry_count=None;self.scan_ok=None

    def fail(self, error):
        if self.error is None:
            self.state, self.error = 'error', str(error)

    def feed(self, data, clock):
        if self.error:
            return []
        if clock >= self.deadline and self.state != 'ready':
            self.fail('UART identity/READY timeout; no retry this startup')
            return []
        self.buffer += data
        if len(self.buffer) > 4096 and b'\n' not in self.buffer:
            self.fail('UART line too long / wrong serial settings')
            return []
        frames = []
        while b'\n' in self.buffer and not self.error:
            line, self.buffer = self.buffer.split(b'\n', 1)
            # FSBL uses LF/CR, App uses CR/LF. A trailing CR after the
            # previous LF belongs to the line boundary, not the next prompt.
            # Strip ONLY boundary CRs; spaces/embedded CRs remain significant.
            line = line.strip(b'\r')
            if line == PROMPT:
                if self.state != 'waiting_prompt':
                    self.fail('Repeated identity prompt; no automatic second submission')
                    break
                try:
                    boot = self.value_factory()  # only AFTER a full fresh prompt
                    self.claim(boot)  # durable no-reuse claim BEFORE transmission
                except Exception as exc:
                    self.fail(f'Identity generation/claim failed: {exc}')
                    break
                self.boot, self.state, self.deadline = boot, 'waiting_ready', clock + 300
                frames.append(f'{boot:08x}\n'.encode('ascii'))
            elif line.startswith(b'S2C READY '):
                m = re.fullmatch(rb'S2C READY boot_id=([0-9a-fA-F]{8}) registry=(\d{1,2}) scan_ok=([01]) scenes=3 roi=any banks=1 UDP=5010 app='+LEGACY_APP_ID.encode(), line)
                if not m or self.state != 'waiting_ready' or int(m[1], 16) != self.boot or int(m[2])>48:
                    self.fail('READY identity/model/App revision mismatch; require model_lifecycle_r1, no old App or hot takeover')
                else:
                    self.state = 'ready';self.registry_count=int(m[2]);self.scan_ok=bool(int(m[3]))
            elif line.startswith(b'S2C boot_id='):
                m = re.fullmatch(rb'S2C boot_id=([0-9a-fA-F]{8}) MODEL_SCAN int16; no inference yet', line)
                if not m or self.state != 'waiting_ready' or int(m[1],16) != self.boot:
                    self.fail('UART MODEL_SCAN identity mismatch; no hot takeover')
            elif line.startswith((b'S2C STOP', b'S2C HALTED', b'S2C PROBE HALTED')):
                self.fail(line.decode('ascii', errors='replace'))
        # Never submit when a repeated prompt/failure was already in this batch.
        return [] if self.error else frames


class SdIdentity:
    """Current boot parser: observes SD reservation; NEVER produces UART TX."""
    def __init__(self,clock,claim,expected_build=None):
        self.state,self.error,self.boot='waiting_record',None,None
        self.buffer=b'';self.deadline=clock+180;self.claim=claim;self.ready_notified=False
        self.registry_count=None;self.scan_ok=None;self.generation=None;self.nonce=None
        self.expected_build=expected_build;self.build=None
    def fail(self,error):
        if self.error is None:self.state,self.error='error',str(error)
    def feed(self,data,clock):
        if self.error:return []
        if clock>=self.deadline and self.state!='ready':self.fail('SD identity/READY timeout; no UART fallback');return []
        self.buffer+=data
        if len(self.buffer)>4096 and b'\n' not in self.buffer:self.fail('UART line too long');return []
        while b'\n' in self.buffer and not self.error:
            line,self.buffer=self.buffer.split(b'\n',1);line=line.strip(b'\r')
            if line.startswith(b'S2C BUILD '):
                if self.build is not None or self.state!='waiting_record':self.fail('Repeated/late App BUILD identity');continue
                try:self.build=uart_build(line.decode('ascii'),self.expected_build)
                except (ValueError,UnicodeError) as exc:self.fail(exc)
            elif line.startswith(b'S2C IDENTITY '):
                m=re.fullmatch(rb'S2C IDENTITY source=sd-journal boot_id=([0-9a-f]{8}) generation=([1-9][0-9]{0,9}) nonce=([0-9a-f]{16}) abi=4',line,re.I)
                if not m or self.state!='waiting_record' or (self.expected_build and not self.build):self.fail('Missing/duplicate/corrupt SD boot reservation or reviewed BUILD identity');continue
                boot=int(m[1],16);generation=int(m[2]);nonce=int(m[3],16)
                if not boot or not nonce or not 0<generation<2**32:self.fail('Invalid SD identity fields');continue
                self.boot,self.generation,self.nonce=boot,generation,f'{nonce:016x}'
                try:self.claim(boot)
                except Exception as exc:self.fail(f'SD boot observation/reuse gate: {exc}');continue
                self.state='waiting_ready';self.deadline=clock+300
            elif line==PROMPT or line.startswith(b'S2B BOOT_ID'):
                self.fail('Old UART-input App refused; no PC identity injection')
            elif line.startswith(b'S2C READY '):
                m=re.fullmatch(rb'S2C READY boot_id=([0-9a-f]{8}) registry=(\d{1,2}) scan_ok=([01]) scenes=3 roi=any banks=1 UDP=5010 app='+APP_ID.encode(),line,re.I)
                if not m or self.state!='waiting_ready' or int(m[1],16)!=self.boot or int(m[2])>48:
                    self.fail('READY does not match observed SD identity/current App')
                else:self.state='ready';self.registry_count=int(m[2]);self.scan_ok=bool(int(m[3]))
            elif line.startswith(b'S2C boot_id='):
                m=re.fullmatch(rb'S2C boot_id=([0-9a-f]{8}) MODEL_SCAN int16; no inference yet',line,re.I)
                if not m or self.state!='waiting_ready' or int(m[1],16)!=self.boot:self.fail('MODEL_SCAN boot mismatch')
            elif line.startswith((b'S2C STOP',b'S2C HALTED',b'S2C PROBE HALTED')):self.fail(line.decode('ascii',errors='replace'))
        return []


class Capture:
    def __init__(self, root, on_ready):
        self.root = Path(root)
        self.on_ready = on_ready
        self.worker = None
        self.cancel = threading.Event()
        self.lock = threading.RLock()
        self.identity = None
        self.out, self.port = None, None
        self.active, self.reason = False, None
        self.released = True
        self.rx_bytes = self.tx_bytes = 0
        self.tail = ''
        self.build_evidence = None
        self.settings = self._last_settings()

    def _last_settings(self):
        """Read last explicitly confirmed, successfully opened port; never scan/open.

        session.json is written only after open succeeds. A malformed latest
        session does not fall back to an older (possibly different) UART.
        """
        try:
            paths=sorted(self.root.glob('capture_*/session.json'),reverse=True)
            if not paths:return None
            d=json.loads(paths[0].read_text(encoding='utf-8'))
            port,baud=d.get('port'),d.get('baudrate')
            if (d.get('operator_confirmed') is not True or d.get('framing')!='8N1'
                or any(d.get(k) is not False for k in ('flow_control','dtr','rts'))
                or not isinstance(port,str) or not re.fullmatch(r'COM[1-9][0-9]{0,3}',port,re.I)
                or type(baud) is not int or baud not in (9600,19200,38400,57600,115200,230400,460800,921600)):
                return None
            return dict(port=port.upper(),baudrate=baud)
        except (OSError,ValueError,TypeError,AttributeError):
            return None

    def snapshot(self):
        with self.lock:
            p = self.identity
            return dict(active=self.active, port_released=self.released, state=p.state if p else 'disconnected',
                        service_app=APP_ID,build=p.build if isinstance(p,SdIdentity) else None,
                        error=p.error if p else None, reason=self.reason, port=self.port,
                        boot_id=f'{p.boot:08x}' if p and p.boot is not None else None,
                        evidence=str(self.out) if self.out else None, rx_bytes=self.rx_bytes,
                        tx_bytes=self.tx_bytes, tail=self.tail, max_seconds=CAPTURE_SECONDS,
                        app=APP_ID if p and p.state=='ready' else None,
                        registry_count=p.registry_count if p else None,scan_ok=p.scan_ok if p else None,
                        settings=dict(self.settings) if self.settings else None)

    @staticmethod
    def ports():
        from serial.tools import list_ports
        return [dict(port=p.device, description=p.description) for p in list_ports.comports()]

    def start(self, port, baudrate, confirmed, build_evidence=None):
        if confirmed is not True:
            raise ValueError('Explicit exclusive UART0/new independent cold-start confirmation required')
        if not isinstance(port,str) or not re.fullmatch(r'COM[1-9][0-9]{0,3}',port,re.I):
            raise ValueError('Choose the existing UART0 COM port explicitly')
        if type(baudrate) is not int or baudrate not in (9600,19200,38400,57600,115200,230400,460800,921600):
            raise ValueError('Select the same baud rate as the existing UART0 terminal')
        with self.lock:
            if self.active or (self.worker and self.worker.is_alive()):
                raise ValueError('UART capture already active; not opening a second connection')
            expected=expected_build(build_evidence)
            self.root.mkdir(parents=True,exist_ok=True)
            self.out = self.root / datetime.now().strftime('capture_%Y%m%d_%H%M%S_%f')
            self.out.mkdir()
            # Freeze the reviewed identity for this capture. A later approved
            # ELF pointer must not relabel an earlier boot's UART evidence.
            (self.out/'elf_audit.json').write_bytes(Path(build_evidence).read_bytes())
            self.port, self.reason, self.tail = port.upper(), None, ''
            self.build_evidence=build_evidence
            self.rx_bytes = self.tx_bytes = 0
            self.cancel.clear()
            def claim(boot):
                if type(boot) is not int or not 0 < boot <= 0xffffffff or boot in (0xe4196b84,0xe86a03b1,0x64ead9e4,0xbb6bd8e3):
                    raise ValueError('Generated identity not usable by current GCS gate; stop, no replacement constant')
                directory=self.root/'identities';directory.mkdir(exist_ok=True)
                with (directory/f'{boot:08x}.json').open('x',encoding='utf-8') as f:
                    json.dump(dict(boot_id=f'{boot:08x}',capture=str(self.out),source='BOARD_SD_JOURNAL',
                        generation=self.identity.generation,nonce=self.identity.nonce),f)
                    f.flush();os.fsync(f.fileno())
            self.identity=SdIdentity(time.monotonic(),claim,expected)
            self.active=True
            self.released=False

        def work():
            serial_port=None
            started=time.monotonic()
            try:
                import serial
                # Configure BEFORE opening; no flow control, BREAK or reset calls.
                # Hardware/OS transients cannot be certified by software alone.
                serial_port=serial.Serial(port=None,baudrate=baudrate,bytesize=8,parity='N',stopbits=1,
                    timeout=.10,write_timeout=1,xonxoff=False,rtscts=False,dsrdtr=False)
                serial_port.dtr=False;serial_port.rts=False;serial_port.port=self.port
                serial_port.open()  # exclusive on Windows; never kill another holder
                (self.out/'session.json').write_text(json.dumps(dict(port=self.port,baudrate=baudrate,
                    framing='8N1',flow_control=False,dtr=False,rts=False,
                    build_evidence=self.build_evidence,
                    operator_confirmed=True,cold_start_verified_by_software=False,
                    max_seconds=CAPTURE_SECONDS,started=datetime.now(timezone.utc).isoformat()),indent=2),encoding='utf-8')
                with self.lock:self.settings=dict(port=self.port,baudrate=baudrate)
                with (self.out/'uart.bin').open('xb') as raw, (self.out/'uart.txt').open('x',encoding='utf-8',newline='') as text, \
                     (self.out/'serial_events.jsonl').open('x',encoding='utf-8') as trace:
                    def record(direction,data):
                        trace.write(json.dumps(dict(direction=direction,monotonic_ns=time.perf_counter_ns(),hex=data.hex()))+'\n');trace.flush()
                    while not self.cancel.is_set():
                        if time.monotonic()-started>=CAPTURE_SECONDS:
                            self.reason=f'{CAPTURE_SECONDS}-second capture limit reached';break
                        data=serial_port.read(4096)
                        if data:
                            raw.write(data);raw.flush()
                            decoded=data.decode('ascii',errors='replace');text.write(decoded);text.flush()
                            record('rx',data)
                        with self.lock:
                            self.rx_bytes+=len(data);self.tail=(self.tail+data.decode('ascii',errors='replace'))[-1600:]
                            if self.rx_bytes>MAX_BYTES:raise ValueError('UART capture size limit reached')
                            frames=self.identity.feed(data,time.monotonic())
                            if frames:raise ValueError('Read-only SD startup capture must never transmit')
                            if self.identity.error:break
                            notify_ready=self.identity.state=='ready' and not self.identity.ready_notified
                            if notify_ready:
                                self.identity.ready_notified=True
                        if notify_ready:
                            self.on_ready(f'{self.identity.boot:08x}')  # permission gate only, no UDP
            except Exception as exc:
                with self.lock:self.identity.fail(f'{type(exc).__name__}: {exc}')
            finally:
                try:
                    if serial_port is not None:serial_port.close()
                    self.released=True
                except Exception as exc:
                    with self.lock:self.identity.fail(f'Port release unconfirmed: {exc}')
                finally:
                    with self.lock:
                        self.active=False
                        if self.cancel.is_set() and not self.reason:self.reason='User ended capture; UART released'
                        (self.out/'summary.json').write_text(json.dumps(self.snapshot(),ensure_ascii=False,indent=2),encoding='utf-8')
        self.worker=threading.Thread(target=work,name='gcs-uart-capture',daemon=False)
        self.worker.start()
        return self.snapshot()

    def stop(self):
        self.cancel.set()
        if self.worker:
            self.worker.join(timeout=3)
            if self.worker.is_alive():raise RuntimeError('UART capture did not exit; port release unconfirmed')
        if not self.released:raise RuntimeError('UART port release unconfirmed; inspect capture error')
        return self.snapshot()
