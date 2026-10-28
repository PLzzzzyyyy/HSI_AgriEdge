"""Display translation contract, without loading cubes/models or board I/O."""
import ast
import copy
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'gcs'),str(ROOT/'tools')]
import display_labels
import server

class LabelsTests(unittest.TestCase):
    def palette(self,scene):return json.loads((ROOT/f'gcs/scenes/{scene}/palette.json').read_text(encoding='utf-8'))
    def test_all_47_names_match_displayed_ids_colors_and_dp_names(self):
        tree=ast.parse((ROOT/'tools/generate_gcs_dp_labels.py').read_text(encoding='utf-8'))
        dp=next(ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='CHINESE_CLASSES' for t in n.targets))
        total=0
        for scene,n in [('longkou',9),('honghu',22),('hanchuan',16)]:
            with self.subTest(scene=scene):
                p=self.palette(scene);original=copy.deepcopy(p)
                names=display_labels.names(scene,p['classes'][1:],p['colors'])
                self.assertEqual(len(names),n);self.assertEqual(p,original)
                self.assertTrue(all(any('\u4e00'<=c<='\u9fff' for c in name) for name in names))
                if scene in dp:self.assertEqual(names,dp[scene])
                self.assertEqual(server.business_metadata(scene)['classes'],names)
                total+=len(names)
        self.assertEqual(total,47)
    def test_scene_api_preserves_raw_names_and_adds_checked_display_names(self):
        for scene in ('longkou','honghu','hanchuan'):
            p=self.palette(scene);info=dict(classes=p['classes'][1:],palette=p['colors'],versions=[])
            raw=copy.deepcopy(info)
            with patch.object(server.eng,'get_scene',return_value=SimpleNamespace(info=lambda:info)),patch.object(server.E,'closed_loop_info',return_value=None):
                response=server.api_scene(scene)
            self.assertEqual(response['classes'],raw['classes']);self.assertEqual(response['palette'],raw['palette'])
            self.assertEqual(response['display_classes'],display_labels.names(scene,raw['classes'],raw['palette']))
    def test_mismatched_ids_or_colors_are_rejected(self):
        p=self.palette('honghu');bad=p['classes'][1:];bad[0],bad[1]=bad[1],bad[0]
        with self.assertRaises(ValueError):display_labels.names('honghu',bad,p['colors'])
        colors=p['colors'][:];colors[1]='#123456'
        with self.assertRaises(ValueError):display_labels.names('honghu',p['classes'][1:],colors)
        with self.assertRaises(ValueError):display_labels.names('unknown',[],[])

if __name__=='__main__':unittest.main()
