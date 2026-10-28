"""Windows desktop launcher; detached web service and logged XSDB download."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / '.runtime-tmp'
URL = 'http://127.0.0.1:8765'
HTTP = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def say(message):
    print(message, flush=True)


def api(path, body=None, timeout=3):
    data = None if body is None else json.dumps(body).encode('utf-8')
    req = urllib.request.Request(URL + path, data=data,
                                 headers={'Content-Type': 'application/json'})
    try:
        with HTTP.open(req, timeout=timeout) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode('utf-8', errors='replace')
        raise RuntimeError(detail) from exc


def state():
    try:
        result = api('/api/state')
        return result if result.get('service') == 'gcs-s2c-roi' else None
    except (OSError, ValueError, RuntimeError):
        return None


def find_xsdb():
    for name in ('HSI_VITIS', 'XILINX_VITIS'):
        if os.environ.get(name):
            path = Path(os.environ[name]) / 'bin/xsdb.bat'
            if path.is_file():
                return path
    for base in ('D:/AMDDesignTools', 'C:/AMDDesignTools', 'D:/AMD', 'C:/AMD',
                 'C:/Xilinx/Vitis', 'D:/Xilinx/Vitis'):
        folder = Path(base)
        if not folder.is_dir():
            continue
        for version in sorted(folder.iterdir(), reverse=True):
            for relative in ('Vitis/bin/xsdb.bat', 'bin/xsdb.bat'):
                path = version / relative
                if path.is_file():
                    return path
    return None


def download(env, stamp):
    xsdb = find_xsdb()
    if xsdb is None:
        say('未找到 XSDB；网页仍会启动。请检查 Vitis 安装目录。')
        return False
    receipt = RUNTIME / ('download_' + stamp + '.ok')
    log = RUNTIME / ('download_' + stamp + '.log')
    env = dict(env, HSI_VITIS=str(xsdb.parent.parent), HSI_DOWNLOAD_RESULT=str(receipt))
    # cmd.exe parses quotes itself; list2cmdline's backslash escaping is not
    # valid for quoted batch paths inside /c.
    command = (f'"{os.environ.get("COMSPEC", "cmd.exe")}" /d /s /c '
               f'""{xsdb}" "{ROOT / "tools/launcher/dl_gcs_demo.tcl"}""')
    say('[2/4] 正在下载板卡固件，约需 30～60 秒。')
    say('下载日志：' + str(log))
    with log.open('wb') as output:
        child = subprocess.Popen(command, cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
                                 stdout=output, stderr=subprocess.STDOUT)
        begin = time.monotonic()
        reported = 0
        while child.poll() is None:
            elapsed = int(time.monotonic() - begin)
            if elapsed >= 180:
                subprocess.run(['taskkill', '/PID', str(child.pid), '/T', '/F'],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
                child.wait(timeout=10)
                say('下载超过 180 秒，已结束本次下载进程。')
                return False
            if elapsed // 10 > reported:
                reported = elapsed // 10
                say(f'  下载进行中……已等待 {elapsed} 秒')
            time.sleep(.25)
    text = log.read_text(encoding='utf-8', errors='replace')
    for line in text.splitlines():
        if line.startswith(('ROOT ', 'APP ', '== ', 'ERROR:')):
            say(line)
    if receipt.is_file() and receipt.read_text().strip() == 'DOWNLOAD_OK':
        say('板卡固件下载完成。')
        return True
    say('板卡下载未完成，网页仍会打开。下载日志末尾：')
    say('\n'.join(text.splitlines()[-12:]))
    return False


def ensure_console(env, stamp):
    existing = state()
    if existing:
        say('[3/4] 已有控制台服务，复用现有服务。')
        return existing
    with socket.socket() as probe:
        if probe.connect_ex(('127.0.0.1', 8765)) == 0:
            raise RuntimeError('8765 端口被其他服务占用，未停止或覆盖该服务。')
    out = RUNTIME / ('console_' + stamp + '.out.log')
    err = RUNTIME / ('console_' + stamp + '.err.log')
    flags = 0
    if os.name == 'nt':
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    with out.open('wb') as stdout, err.open('wb') as stderr:
        child = subprocess.Popen([sys.executable, '-u', str(ROOT / 'tools/gcs_roi.py'),
                                  'serve', '--port', '8765'], cwd=ROOT, env=env,
                                 stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr,
                                 creationflags=flags, close_fds=True)
    say('[3/4] 控制台在后台启动；关闭本窗口不会关闭网页服务。')
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        ready = state()
        if ready:
            return ready
        if child.poll() is not None:
            break
        time.sleep(.5)
    raise RuntimeError('控制台启动失败。日志：' + str(err) + '\n' +
                       err.read_text(encoding='utf-8', errors='replace')[-2500:])


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    mode = sys.argv[1].lower() if len(sys.argv) > 1 else 'console'
    if mode not in ('console', 'skipload'):
        raise ValueError('模式应为 console 或 skipload。')
    RUNTIME.mkdir(exist_ok=True)
    stamp = time.strftime('%Y%m%d_%H%M%S') + '_' + str(os.getpid())
    env = dict(os.environ, GCS_LOCAL_DEMO='1', PYTHONUTF8='1',
               TEMP=str(RUNTIME), TMP=str(RUNTIME), TMPDIR=str(RUNTIME))
    bundle = ROOT / 'build/host/gcs_parcel_temp_mirror_20261018_v3'
    if (bundle / 'manifest.json').is_file():
        env['GCS_LOCAL_DEMO_BUNDLE'] = str(bundle)
    key_dir=ROOT/'firmware/keys_20261018'
    marker=key_dir/'deployment.json'
    if marker.is_file():
        import hashlib
        deployment=json.loads(marker.read_text(encoding='utf-8'))
        required={'tt_gcs_keys.bit','tt_gcs_keys.xsa','fsbl_a53.elf','gcs_keys.elf'}
        if set(deployment['files'])!=required:raise ValueError('按键固件套件不完整')
        for name,expected in deployment['files'].items():
            if hashlib.sha256((key_dir/name).read_bytes()).hexdigest()!=expected:
                raise ValueError('按键固件套件校验失败：'+name)
        selected=ROOT/deployment['bundle']
        if json.loads((selected/'manifest.json').read_text(encoding='utf-8'))['release_id']!=deployment['release_id']:
            raise ValueError('按键固件与控制台身份不匹配')
        env['GCS_LOCAL_DEMO_BUNDLE']=str(selected)
        env['HSI_FIRMWARE_SET']=str(key_dir)
    env.pop('PYTHONHOME', None)
    env.pop('PYTHONPATH', None)
    say('农情分析系统 — 一键启动')
    say('[1/4] Python：' + sys.executable)
    existing = state()
    running = bool(existing and (existing.get('run') or {}).get('status') in ('running', 'paused'))
    loaded = False
    board_ok = running or mode == 'skipload'
    if running:
        say('已有推理任务正在运行，保留任务并打开现有控制台。')
    elif mode != 'skipload':
        if existing and existing['source'].get('active'):
            api('/api/board/session/close', {}, timeout=10)
        loaded = download(env, stamp)
    else:
        say('[2/4] 只启动网页，不重新下载板卡固件。')
    ensure_console(env, stamp)
    if loaded:
        say('正在核对板卡启动状态……')
        try:
            for attempt in range(4):
                try:
                    connected = api('/api/board/connect', {'confirmed': True, 'boot_method': 'jtag'}, timeout=50)
                    if connected.get('ready') or attempt == 3:
                        break
                except (OSError, RuntimeError) as exc:
                    if attempt == 3 or 'timeout' not in str(exc).lower():
                        raise
                say('  板卡仍在初始化，稍后重读启动记录……')
                time.sleep(2)
            startup = connected.get('discovery', {}).get('startup', {})
            if connected.get('ready'):
                say('板卡已连接；DP 初始化返回码：' + str(startup.get('dp_rc')))
                board_ok = startup.get('dp_rc') == 0
            else:
                say('板卡尚未就绪，请在网页“链路与下发”查看启动状态。')
        except (OSError, ValueError, RuntimeError) as exc:
            say('网页已启动，板卡连接需要检查：' + str(exc))
    say('[4/4] 控制台地址：' + URL + '/')
    if not os.environ.get('HSI_NO_BROWSER'):
        webbrowser.open(URL + '/')
    say('网页服务已就绪。可以关闭本启动窗口。')
    if not board_ok:
        say('网页已打开，但板卡或 DP 尚未就绪，请保留上方错误与下载日志。')
    return 0 if board_ok else 1


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        say('启动失败：' + str(exc))
        raise SystemExit(1)
