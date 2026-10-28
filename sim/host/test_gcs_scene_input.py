"""Read-only input contract; fixtures, no models/devices/server."""
from pathlib import Path
import hashlib
import sys
import tempfile
import unittest
import numpy as np
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'gcs'))
import scene_input


class InputTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.folder = self.root / 'longkou'
        self.folder.mkdir()
        self.cube = np.zeros((11, 12, 270), dtype='<f4')
        self.cube[3:8, 3:9] = np.arange(5 * 6 * 270).reshape(5, 6, 270) / 1000
        self.file = self.folder / 'cube_f32.bin'
        self.file.write_bytes(self.cube.tobytes())
        self.write_meta()
        self.reader = scene_input.InputReader(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def write_meta(self):
        digest = hashlib.sha256(self.file.read_bytes()).hexdigest()
        (self.folder / 'meta.txt').write_text(
            f'H=5\nW=6\npad=3\nbands=270\ncube_bytes={self.file.stat().st_size}\n'
            f'sha256:cube_f32.bin={digest}\n', encoding='utf-8')

    def test_exact_spectrum_corner_padding_and_provenance(self):
        for row, col in ((0, 0), (2, 3), (4, 5)):
            p = self.reader.point('longkou', row, col)
            np.testing.assert_array_equal(p['spectrum'], self.cube[row + 3, col + 3])
            self.assertEqual(p['band_indices'], list(range(270)))
            self.assertEqual(p['rgb_bands'], [112, 67, 31])
            rgb, valid = np.asarray(p['patch_rgb']), np.asarray(p['patch_valid'])
            self.assertEqual(rgb.shape, (7, 7, 3))
            self.assertEqual(valid[3, 3], 1)
            self.assertTrue((rgb[valid == 0] == 0).all())
            self.assertFalse(p['board_returned'])
            self.assertFalse(p['pc_model_inference'])
            self.assertEqual(p['source']['bytes'], self.file.stat().st_size)
            self.assertEqual(p['source']['sha256'], hashlib.sha256(self.file.read_bytes()).hexdigest())
            self.assertIsNone(p['wavelengths_nm'])

    def test_reject_invalid_coordinates_and_paths_not_clamp(self):
        for row, col in ((-1, 0), (5, 0), (0, 6), (True, 0), (0, 1.5)):
            with self.assertRaises(ValueError):
                self.reader.point('longkou', row, col)
        for scene in ('../longkou', 'unknown', ''):
            with self.assertRaises(ValueError):
                self.reader.point(scene, 0, 0)

    def test_missing_truncated_or_changed_file_fails_closed(self):
        self.reader.point('longkou', 1, 1)
        original = self.file.read_bytes()
        self.file.write_bytes(original[:-4])
        with self.assertRaises(ValueError): self.reader.point('longkou', 1, 1)
        self.file.write_bytes(bytes([original[0] ^ 1]) + original[1:])
        with self.assertRaises(ValueError): self.reader.point('longkou', 1, 1)
        self.file.unlink()
        with self.assertRaises(OSError): self.reader.point('longkou', 1, 1)

    def test_changed_meta_and_nonfinite_patch_are_rejected(self):
        self.reader.point('longkou', 1, 1)
        self.cube[4, 4, 0] = np.nan
        self.file.write_bytes(self.cube.tobytes())
        self.write_meta()
        with self.assertRaises(ValueError): self.reader.point('longkou', 1, 1)
        (self.folder / 'meta.txt').write_text('H=999\n', encoding='utf-8')
        with self.assertRaises(ValueError): self.reader.point('longkou', 1, 1)


if __name__ == '__main__': unittest.main(verbosity=2)
