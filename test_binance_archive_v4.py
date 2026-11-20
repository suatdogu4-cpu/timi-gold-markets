"""Offline unit tests of official Binance Vision ZIP integrity and patch safety."""
from __future__ import annotations
import csv
from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO, StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, main
from unittest.mock import patch
import json
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import binance_vision_archive as mod
from tools import install_binance_v4 as patcher

NOW = datetime(2026, 11, 20, 13, 30, tzinfo=timezone.utc)
FIRST = 1767657600 # 2026-01-06 UTC


def pack_zip(filename,rows):
    out=StringIO()
    writer=csv.writer(out)
    writer.writerow(['open_time','open','high','low','close','volume','close_time'])
    writer.writerows(rows)
    mem=BytesIO()
    with zipfile.ZipFile(mem,'w',zipfile.ZIP_DEFLATED) as z:
        z.writestr(filename.replace('.zip','.csv'),out.getvalue())
    data=mem.getvalue()
    checksum=f'{sha256(data).hexdigest()}  {filename}\n'.encode()
    return data,checksum


class BinanceVisionTests(TestCase):
    def test_official_paths_only_and_closed_day_only(self):
        packages=mod.packages(NOW)
        self.assertTrue(packages)
        self.assertTrue(any(p[0]=='monthly' and p[1]=='2026-01' for p in packages))
        self.assertEqual(packages[-1][1],'2026-11-19')
        self.assertTrue(all('/futures/um/' in p[2] and '/XAUUSDT/1h/' in p[2] for p in packages))
        self.assertFalse(any('2026-11-20' in p[2] for p in packages))
        with self.assertRaises(ValueError):mod.fetch_official('https://non-official.example/x.zip')

    def test_header_and_open_candle_are_discarded(self):
        fname='XAUUSDT-1h-2026-11-19.zip'
        valid_ms=1795046400*1000 # 2026-11-19 UTC
        unfinished=int(NOW.timestamp()//3600*3600)*1000
        rows=[(valid_ms,4070,4090,4060,4080,22,valid_ms+3599999),
              (unfinished,4075,4095,4065,4085,2,unfinished+3599999),
              ('garbled',1,2,0.5,1,4,1)]
        data,_=pack_zip(fname,rows)
        candles=mod.parse_h1_zip(data,fname,int(NOW.timestamp()))
        self.assertEqual(len(candles),1)
        self.assertEqual(candles[0]['c'],4080)

    def test_checksum_validation_rejects_mutated_zip(self):
        filename='XAUUSDT-1h-2026-10.zip'
        data,checksum=pack_zip(filename,[(1790812800*1000,4000,4010,3990,4005,12,0)])
        def ok_fetch(url):return checksum if url.endswith('.CHECKSUM') else data
        with patch.object(mod,'fetch_official',side_effect=ok_fetch):
            rows,status=mod._validated_zip(mod.BASE+'/monthly/klines/XAUUSDT/1h/'+filename,int(NOW.timestamp()))
        self.assertEqual(status,'VERIFIED');self.assertEqual(len(rows),1)
        with patch.object(mod,'fetch_official',side_effect=lambda url:checksum if url.endswith('CHECKSUM') else data+b'x'):
            with self.assertRaises(mod.Unavailable) as e:
                mod._validated_zip(mod.BASE+'/monthly/klines/XAUUSDT/1h/'+filename,int(NOW.timestamp()))
        self.assertEqual(e.exception.code,'BAD_CHECKSUM')

    def test_http451_fails_closed_and_preserves_old_data(self):
        with TemporaryDirectory() as temp:
            root=Path(temp);csvfile=root/'data/binance_xauusdt_h1.csv'
            csvfile.parent.mkdir(parents=True,exist_ok=True)
            csvfile.write_text('t,o,h,l,c,v\n1790812800,4000,4010,3990,4002,9\n',encoding='utf-8')
            with patch.object(mod,'fetch_official',side_effect=mod.Unavailable(451,'restricted')):
                status=mod.collect_official_archive(csvfile,root,'Binance REST HTTP Error 451',NOW)
            self.assertEqual(status['status'],'ARCHIVE_RESTRICTED')
            self.assertEqual(status['h1_saved'],1)
            self.assertIn('451',status['errors'][0])
            with csvfile.open(encoding='utf-8',newline='') as f:
                self.assertEqual(len(list(csv.DictReader(f))),1)
            health=json.loads((root/'models/gold_ml_v3_source_health.json').read_text())
            self.assertEqual(health['binance_xauusdt']['status'],'ARCHIVE_RESTRICTED')

    def test_404_does_not_fake_bitget_candles(self):
        with TemporaryDirectory() as temp:
            root=Path(temp);dest=root/'data/binance_xauusdt_h1.csv'
            with patch.object(mod,'fetch_official',return_value=None):
                status=mod.collect_official_archive(dest,root,'REST HTTP 451',NOW)
            self.assertEqual(status['h1_saved'],0)
            self.assertEqual(status['status'],'NO_OFFICIAL_ARCHIVE_DATA')
            self.assertFalse(dest.exists())

    def test_installer_safe_anchors(self):
        pipeline='''        response=_get_json('https://fapi.binance.com/fapi/v1/klines?'+params)\n    print('BINANCE_HISTORY',json.dumps(result,ensure_ascii=False))\n    manifest=ARCHIVE/'manifest.json'\n        'sources':all_reports,'storage':storage,'errors':errors,'no_trade':True,'no_live_prediction':True}\n'''
        ui=''' function multiModelResearchPanel(report){\n   const sources=Object.entries(report.sources||{});\n  const rows=models.map(([name,val])=>{const t=val.final_holdout||{};\n        return `<div class="qh-card"><span>${escape(name)}</span><strong>${t.accuracy_pct==null?'—':'%'+escape(n(t.accuracy_pct))}</strong><small>İleri test ${escape(n(t.samples))} örnek · Brier ${escape(n(t.brier))} · Referans ${escape(n(t.baseline_brier))}</small></div>`\n  });\n return `<p class="qh-muted">Doğrulama dönemine göre seçilen model: <p class="qh-muted">Model eğitim raporu UTC: ${candidate}${error}${xgbResearchPanel(ai.ml)}`;\n'''
        p=patcher.patch_pipeline(pipeline)
        u=patcher.patch_ui(ui)
        self.assertIn('collect_official_archive',p)
        self.assertIn('source_health',p)
        self.assertIn('Eski XGBoost v1',u)
        self.assertIn('modelAuditCard',u)
        self.assertIn('Kaynak erişimi',u)
        self.assertEqual(patcher.patch_index('gold_quant_hub.js?v=3400'),'gold_quant_hub.js?v=3500')
        output=patcher.patch_report_reader("'storage':raw.get('storage',{}),'signal_policy':'NO_V3_LIVE_SIGNAL'}")
        self.assertIn('source_health',output)

if __name__=='__main__':main()
