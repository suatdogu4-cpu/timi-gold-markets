"""Safe installer regression tests, without network or market orders."""
from pathlib import Path
import tempfile
import unittest
from install_gold_projection_tab import patch, OLD_GO, APP, INDEX, PROJECTION


def fixture(root):
    (root/APP).write_text('''const navs=[['quant30','◷ 30G Fiyat–Zaman'],['projection','↗ Fiyat Projeksiyonu']];
'''+ OLD_GO + '''
if(name==='analysis-menu'||name==='more-menu'){
  const menus=name==='analysis-menu'?[['quanthub','◈','7 Quant + Konsensüs'],['decision','◎','Karar Motoru']]:[];
  const groups=[['Matematik & Quant',['quant','freqtrade','altinquant','quanthub']]];
}
function uxUpdateDock(k){const group=['technical','smc','flow','depth','quant','freqtrade','altinquant','quanthub','decision'].includes(k)?'analysis':'more';}
''',encoding='utf-8')
    (root/INDEX).write_text('''<html><body><div class="wrap">
<section class="view" id="v-dashboard">DASHBOARD</section>
<section class="view" id="v-quanthub">QUANTHUB</section>
</div></body></html>''',encoding='utf-8')
    (root/PROJECTION).write_text('''<html><head><style>body{color:#fff}</style><script defer src="/gold_projection.js?v=1001"></script></head><body>Projections</body></html>''',encoding='utf-8')

class ProjectionTabTests(unittest.TestCase):
    def test_new_internal_view_and_mobile_menu(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);fixture(root)
            self.assertTrue(patch(root))
            app=(root/APP).read_text()
            idx=(root/INDEX).read_text()
            html=(root/PROJECTION).read_text()
            self.assertIn('id="v-projection"',idx)
            self.assertIn("['quant','freqtrade','altinquant','quanthub','projection']",app)
            self.assertIn("['projection','↗','Fiyat Projeksiyonu']",app)
            self.assertIn('classList.add(\'projection-embedded\')',html)
            self.assertNotIn('window.location.assign(\'/gold-projection\')',app)
            self.assertIn('src="/gold-projection?embed=1"',idx)
            self.assertIn('ResizeObserver',idx)
            self.assertFalse(patch(root))

    def test_unexpected_js_aborts_without_changes(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);fixture(root)
            file=root/APP;file.write_text('Broken JS',encoding='utf-8')
            before={p:(root/p).read_text() for p in (APP,INDEX,PROJECTION)}
            with self.assertRaises(RuntimeError):patch(root)
            self.assertEqual(before,{p:(root/p).read_text() for p in (APP,INDEX,PROJECTION)})

    def test_missing_source_aborts_without_changes(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);fixture(root)
            (root/PROJECTION).unlink()
            with self.assertRaises(RuntimeError):patch(root)

if __name__=='__main__':unittest.main()
