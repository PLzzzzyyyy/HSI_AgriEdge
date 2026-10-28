"""Verified local input display only. No model, GPU, serial or UDP dependency.

cube_f32 is Gaussian/global-normalized input, before patch normalization and
board BFP quantization. It is NOT raw sensor reflectance or a board readback.
"""
import hashlib
from pathlib import Path
import re
import threading
import zlib

import numpy as np


class InputReader:
    SCENES = ('longkou', 'honghu', 'hanchuan')
    # Same zero-based display bands as model/scenes.py; not calibrated RGB.
    RGB = (112, 67, 31)

    def __init__(self, root):
        self.root = Path(root)
        self._verified = {}
        self._lock = threading.Lock()

    @staticmethod
    def _stamp(path):
        s = path.stat()
        return (s.st_size, s.st_mtime_ns, s.st_ctime_ns)

    def _manifest(self, scene):
        if scene not in self.SCENES:
            raise ValueError('Unknown input scene')
        folder = self.root / scene
        meta_path, path = folder / 'meta.txt', folder / 'cube_f32.bin'
        with self._lock:
            stamp = self._stamp(meta_path), self._stamp(path)
            cached = self._verified.get(scene)
            if cached and cached[0] == stamp:
                return path, stamp, cached[1], cached[2]
            kv = dict(line.split('=', 1) for line in meta_path.read_text(encoding='utf-8-sig').splitlines() if '=' in line)
            try:
                H, W, pad, bands, size = (int(kv[k]) for k in ('H', 'W', 'pad', 'bands', 'cube_bytes'))
                expected = kv['sha256:cube_f32.bin'].lower()
            except (KeyError, ValueError) as exc:
                raise ValueError('Incomplete cube manifest') from exc
            if not (0 < H <= 10000 and 0 < W <= 10000 and pad == 3 and bands == 270):
                raise ValueError('Unsupported cube dimensions/padding/bands')
            if size != (H + 6) * (W + 6) * bands * 4 or stamp[1][0] != size:
                raise ValueError('Cube byte size differs from manifest/dimensions')
            if not re.fullmatch('[0-9a-f]{64}', expected):
                raise ValueError('Cube SHA256 missing or invalid')
            sha, crc = hashlib.sha256(), 0
            with path.open('rb') as stream:
                for chunk in iter(lambda: stream.read(1 << 20), b''):
                    sha.update(chunk)
                    crc = zlib.crc32(chunk, crc)
            if sha.hexdigest() != expected:
                raise ValueError('Cube SHA256 differs from manifest; no fallback')
            if stamp != (self._stamp(meta_path), self._stamp(path)):
                raise ValueError('Input changed during verification; retry after file writes finish')
            provenance = dict(path=str(path.resolve()), bytes=size, sha256=expected, crc32=f'{crc:08x}',
                              kind='local_preprocessed_float32_cube', manifest=str(meta_path.resolve()),
                              processing='Gaussian + global normalization; before patch normalization/BFP quantization')
            dims = (H, W, pad, bands)
            self._verified[scene] = (stamp, dims, provenance)
            return path, stamp, dims, provenance

    def point(self, scene, row, col):
        if type(row) is not int or type(col) is not int:
            raise ValueError('Integer row/col required')
        path, stamp, (H, W, pad, bands), provenance = self._manifest(scene)
        if not (0 <= row < H and 0 <= col < W):
            raise ValueError('Point outside scene; coordinates are not clamped')
        cube = np.memmap(path, dtype='<f4', mode='r', shape=(H + 6, W + 6, bands))
        try:
            patch = np.array(cube[row:row + 7, col:col + 7], copy=True)
        finally:
            cube._mmap.close()
        if stamp != (self._stamp(path.parent / 'meta.txt'), self._stamp(path)):
            raise ValueError('Input changed during read; no stale display')
        if not np.isfinite(patch).all():
            raise ValueError('Non-finite input patch')
        rr, cc = np.mgrid[row - 3:row + 4, col - 3:col + 4]
        valid = (rr >= 0) & (rr < H) & (cc >= 0) & (cc < W)
        rgb = patch[:, :, self.RGB]
        lo, hi = rgb[valid].min(axis=0), rgb[valid].max(axis=0)
        # Contrast is display-only and per-window; keep source spectrum exact.
        rgb = np.round(np.clip((rgb - lo) / np.maximum(hi - lo, 1e-12), 0, 1) * 255).astype(np.uint8)
        rgb[~valid] = 0
        return dict(scene=scene, row=row, col=col, source=dict(provenance),
                    board_returned=False, pc_model_inference=False, wavelengths_nm=None,
                    band_indices=list(range(bands)), spectrum=patch[pad, pad].tolist(),
                    rgb_bands=list(self.RGB), patch_rgb=rgb.tolist(), patch_valid=valid.astype(np.uint8).tolist(),
                    rgb_mapping='per-window per-channel min/max on valid pixels; zero padding black')
