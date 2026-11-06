import sys,tempfile,json,re,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from app import create_app

class ExternalTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
  self.app=create_app({'DATABASE_PATH':str(self.root/'db'),'SECRET_KEY':'x'*40,'MAIL_MODE':'console'})
  self.c=TestClient(self.app)
  self.post('signup',{'email':'test@example.com','username':'test','display_name':'Test','password':'long-password-123'})
  code=re.findall(r'code is (\d+)',(self.root/'mailbox.log').read_text())[-1]
  assert self.post('verify',{'code':code}).status_code==200
 def tearDown(self):self.c.close();self.tmp.cleanup()
 def post(self,p,d):return self.c.post('/api/'+p,json=d,headers={'X-CSRF-Token':self.c.get('/api/session').json()['csrf']})
 def test_games(self):
  self.assertEqual(set(self.c.get('/api/session').json()['games']),{'sudoku','memory','word','trivia','pokemon'})
 def test_all_quizzes_server_scored(self):
  def provider(url,params=None):
   if 'opentdb' in url:return {'response_code':0,'results':[{'question':'Question','correct_answer':'yes','incorrect_answers':['no','maybe','never']}] * 10}
   if 'dictionaryapi' in url:return [{'meanings':[{'definitions':[{'definition':'A useful clue without the answer.'}]}]}]
   return {'name':'creature'+url.rsplit('/',1)[-1],'sprites':{'front_default':'https://example.com/sprite.png'}}
  for game in ['word','trivia','pokemon']:
   with patch('external_games.fetch',side_effect=provider):
    response=self.post('external/start',{'game':game});self.assertEqual(response.status_code,200,response.text);r=response.json()
   self.assertNotIn('answer',r)
   while True:
    with self.app.state.db() as con:p=json.loads(con.execute('SELECT payload FROM runs WHERE id=?',(r['id'],)).fetchone()[0])
    answer=p['questions'][p['index']]['answer']
    x=self.post('external/'+r['id']+'/action',{'answer':answer});self.assertEqual(x.status_code,200,x.text)
    self.assertEqual(self.post('external/'+r['id']+'/action',{'answer':answer}).status_code,400)
    x=self.post('external/'+r['id']+'/action',{'action':'next'});self.assertEqual(x.status_code,200,x.text)
    if x.json()['done']:break
   self.assertEqual(x.json()['score'],len(p['questions']))
   self.assertEqual(self.post('external/'+r['id']+'/action',{'action':'next'}).status_code,409)
 def test_memory(self):
  with patch('external_games.fetch',return_value={'success':True,'cards':[{'code':str(i)+'S'} for i in range(6)]}):r=self.post('external/start',{'game':'memory'}).json()
  with self.app.state.db() as con:p=json.loads(con.execute('SELECT payload FROM runs WHERE id=?',(r['id'],)).fetchone()[0])
  self.assertNotIn('cards',r)
  for card in set(p['cards']):
   for i,c in enumerate(p['cards']):
    if c==card:res=self.post('external/'+r['id']+'/action',{'index':i})
  self.assertTrue(res.json()['done']);self.assertEqual(res.json()['score'],6)
 def test_sudoku(self):
  solution=[[(y*3+y//3+x)%9+1 for x in range(9)] for y in range(9)];board=[row[:] for row in solution];board[0][0]=0
  with patch('external_games.fetch',return_value={'newboard':{'grids':[{'value':board,'solution':solution,'difficulty':'Easy'}]}}):r=self.post('external/start',{'game':'sudoku'}).json()
  self.assertNotIn('solution',r)
  self.assertEqual(self.post('external/'+r['id']+'/action',{'board':board}).status_code,400)
  self.assertTrue(self.post('external/'+r['id']+'/action',{'board':solution}).json()['done'])
 def test_outage_no_fake_round(self):
  from fastapi import HTTPException
  with patch('external_games.fetch',side_effect=HTTPException(503,'Unavailable')):self.assertEqual(self.post('external/start',{'game':'memory'}).status_code,503)
  self.assertEqual(self.c.get('/api/stats').json()['total'],0)
 def test_archived_records_hidden(self):
  self.assertEqual(self.c.get('/api/leaderboard?game=snake').status_code,400)
  self.assertEqual(self.c.get('/api/stats').json()['results'],[])
if __name__=='__main__':unittest.main()
