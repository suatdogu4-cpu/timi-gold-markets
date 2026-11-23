"""Offline tests for safe idempotent GitHub installer."""
import tempfile
import unittest
from pathlib import Path
from install_gold_projection import patch

class InstallTests(unittest.TestCase):
    def setup_repo(self,root):
        (root/'main.py').write_text("from fastapi.responses import FileResponse\nROOT=Path(__file__)\nregister_gold30(app, M, closed_bars, quant_hub_daily_history)\n",encoding='utf-8')
        (root/'gold_app.js').write_text("const navs=[['quant30','◷ 30G Fiyat–Zaman']];\nfunction go(k){if(k==='quant30'){window.location.assign('/gold30');return}page=k;",encoding='utf-8')
        (root/'gold_projection.html').write_text('<html></html>',encoding='utf-8')
        (root/'gold_projection.js').write_text("'use strict';",encoding='utf-8')
        (root/'gold30_quant.py').write_text('# module',encoding='utf-8')
    def test_idempotent_install(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);self.setup_repo(p)
            self.assertTrue(patch(p));main=(p/'main.py').read_text();js=(p/'gold_app.js').read_text()
            self.assertFalse(patch(p));self.assertEqual(main,(p/'main.py').read_text());self.assertEqual(js,(p/'gold_app.js').read_text())
            self.assertIn("@app.get('/gold-projection'",main)
            self.assertIn("['projection','↗ Fiyat Projeksiyonu']",js)
    def test_fail_closed(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);self.setup_repo(p)
            before=(p/'main.py').read_text()
            (p/'gold_app.js').write_text('BAD MENU',encoding='utf-8')
            with self.assertRaises(RuntimeError):patch(p)
            self.assertEqual(before,(p/'main.py').read_text())
    def test_missing_files(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(RuntimeError):patch(Path(d))

if __name__=='__main__':unittest.main()
