import unittest,tempfile,re
from pathlib import Path
from fastapi.testclient import TestClient
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app import create_app
ROOT=Path(__file__).resolve().parents[1]
class ArcadeTests(unittest.TestCase):
 def test_embedding_headers_and_local_assets(self):
  with tempfile.TemporaryDirectory() as d:
   c=TestClient(create_app({'DATABASE_PATH':d+'/db','SECRET_KEY':'t'*40,'MAIL_MODE':'console'}))
   for game in ('bird','platformer'):
    url='/static/vendor/'+game+'/'
    res=c.get(url+'index.html');self.assertEqual(res.status_code,200)
    self.assertEqual(res.headers['x-frame-options'],'SAMEORIGIN')
    self.assertIn("frame-ancestors 'self'",res.headers['content-security-policy'])
    for ref in re.findall(r'(?:src|href)="([^"#]+)"',res.text):
     self.assertFalse(ref.startswith('http'))
     self.assertEqual(c.get(url+ref).status_code,200,ref)
   self.assertEqual(c.get('/login').headers['x-frame-options'],'DENY')
 def test_game_sources_have_no_navigation_or_ad_sdks(self):
  for game in ('bird','platformer'):
   for p in (ROOT/'static/vendor'/game/'js').rglob('*.js'):
    if p.name=='melonJS-min.js':continue
    self.assertNotRegex(p.read_text(),r'window\.open\s*\(|(?:window\.)?location\s*(?:=|\.href\s*=)|googlesyndication|gdsdk|adsbygoogle')
 def test_platformer_map_images_exist(self):
  import xml.etree.ElementTree as ET
  for p in (ROOT/'static/vendor/platformer/data/map').glob('*.tmx'):
   for element in ET.parse(p).iter('image'):
    self.assertTrue((p.parent/element.attrib['source']).resolve().is_file())
if __name__=='__main__':unittest.main()
