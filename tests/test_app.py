import json
import re
import sqlite3
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from app import create_app, password_matches
from game_models import Memory, Random, Snake, computer_move, typing_result, winner


class RulesTests(unittest.TestCase):
    def test_snake_replay_and_collision(self):
        a, b = Snake(98), Snake(98)
        self.assertEqual(a.food,b.food)
        a.food = (7,7)
        a.step()
        self.assertEqual(a.score,10)
        self.assertEqual(len(a.body),4)
        a.turn(-1,0)
        self.assertEqual(a.next_direction,(1,0))
        for _ in range(30): a.step()
        self.assertFalse(a.alive)

    def test_memory_all_pairs_and_ignored_taps(self):
        m = Memory(42)
        self.assertEqual(m.choose(0),'first')
        self.assertEqual(m.choose(0),'ignored')
        m = Memory(42)
        for symbol in range(6):
            pair=[i for i,c in enumerate(m.cards) if c==symbol]
            self.assertEqual(m.choose(pair[0]),'first')
            self.assertEqual(m.choose(pair[1]),'match')
        self.assertTrue(m.complete)
        self.assertEqual(m.moves,6)

    def test_computer_wins_and_blocks(self):
        self.assertEqual(computer_move(['O','O','','X','X','','','','']),2)
        self.assertEqual(computer_move(['X','X','','','O','','','','']),2)
        self.assertEqual(winner(['X','O','X','O','X','O','O','X','O']),'draw')

    def test_typing_accuracy_and_wpm(self):
        self.assertEqual(typing_result('hello','hello',30),{'score':2.0,'accuracy':100.0,'characters':5})
        self.assertEqual(typing_result('heXlo','hello',60)['accuracy'],80.0)


class APITests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.folder=Path(self.temp.name)
        self.app=create_app({'DATABASE_PATH':str(self.folder/'test.sqlite3'),'SECRET_KEY':'test-key'*8,'MAIL_MODE':'console','TRIVIA_API_ENABLED':False})
        self.client=TestClient(self.app)
        self.token=self.client.get('/api/session').json()['csrf']

    def tearDown(self):
        self.client.close()
        self.temp.cleanup()

    def post(self,path,data=None,client=None):
        c=client or self.client
        token=c.get('/api/session').json()['csrf']
        return c.post('/api/'+path,json=data or {},headers={'X-CSRF-Token':token})

    def code(self):
        return re.findall(r'code is (\d{6})', (self.folder/'mailbox.log').read_text())[-1]

    def register(self,email='gavi@example.com',username='gavi',client=None):
        res=self.post('signup',{'display_name':'Gavi','username':username,'email':email,'password':'long-password-123'},client)
        self.assertEqual(res.status_code,200,res.text)
        code=self.code()
        res=self.post('verify',{'code':code},client)
        self.assertEqual(res.status_code,200,res.text)
        return self.client.get('/api/session').json()['user'] if client is None else client.get('/api/session').json()['user']

    def test_new_account_verification_private_data_and_csrf(self):
        denied=self.client.post('/api/signup',json={})
        self.assertEqual(denied.status_code,403)
        self.assertEqual(self.client.get('/api/stats').status_code,401)
        self.post('signup',{'display_name':'Gavi','username':'gavi','email':'gavi@example.com','password':'long-password-123'})
        self.assertIsNone(self.client.get('/api/session').json()['user'])
        self.assertNotIn(self.code(),self.client.get('/api/session').text)
        self.assertEqual(self.post('verify',{'code':'bad'}).status_code,400)
        self.assertEqual(self.post('verify',{'code':self.code()}).status_code,200)
        self.assertEqual(self.client.get('/api/stats').json()['total'],0)
        with self.app.state.db() as con:
            stored=con.execute('SELECT password FROM users').fetchone()[0]
        self.assertNotIn('long-password',stored)
        self.assertTrue(password_matches('long-password-123',stored))
        self.assertEqual(self.post('verify',{'code':self.code()}).status_code,400)

    def test_code_attempt_limit_and_resend_cooldown(self):
        self.post('signup',{'display_name':'Gavi','username':'gavi','email':'gavi@example.com','password':'long-password-123'})
        self.assertEqual(self.post('resend').status_code,429)
        for _ in range(5):self.post('verify',{'code':'not-a-code'})
        self.assertEqual(self.post('verify',{'code':self.code()}).status_code,400)

    def test_login_rotation_logout_and_password_recovery(self):
        self.register()
        old_cookie=self.client.cookies.get('infinitrix')
        self.post('logout')
        self.assertEqual(self.client.get('/api/stats').status_code,401)
        self.assertEqual(self.post('login',{'email':'gavi@example.com','password':'wrong'}).status_code,401)
        self.assertEqual(self.post('login',{'email':'gavi@example.com','password':'long-password-123'}).status_code,200)
        self.assertNotEqual(old_cookie,self.client.cookies.get('infinitrix'))
        other=TestClient(self.app)
        self.post('login',{'email':'gavi@example.com','password':'long-password-123'},other)
        self.post('forgot',{'email':'gavi@example.com'})
        self.post('verify',{'code':self.code()})
        self.assertEqual(self.post('reset-password',{'password':'new-password-123'}).status_code,200)
        self.assertEqual(other.get('/api/stats').status_code,401)
        self.assertEqual(self.post('login',{'email':'gavi@example.com','password':'new-password-123'}).status_code,200)
        other.close()

    def test_expired_code_rejected(self):
        self.post('signup',{'display_name':'Gavi','username':'gavi','email':'gavi@example.com','password':'long-password-123'})
        with self.app.state.db() as con:con.execute('UPDATE challenges SET expires=0')
        self.assertEqual(self.post('verify',{'code':self.code()}).status_code,400)

    def test_memory_score_replay_privacy_and_duplicate_save(self):
        self.register()
        r=self.post('runs/start',{'game':'memory'}).json()
        m=Memory(r['seed'])
        actions=[]
        for card in range(6):actions += [i for i,c in enumerate(m.cards) if c==card]
        payload={'actions':actions,'score':999999}
        result=self.post('runs/'+r['id']+'/finish',payload)
        self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(result.json()['score'],6)
        self.assertEqual(self.post('runs/'+r['id']+'/finish',payload).status_code,409)
        stats=self.client.get('/api/stats').json()
        self.assertEqual(stats['total'],1)
        ranks=self.client.get('/api/leaderboard?game=memory').json()
        self.assertEqual(ranks['position']['rank'],1)
        self.assertNotIn('email',ranks['players'][0])
        self.assertEqual(self.client.get('/api/players/gavi').status_code,404)
        settings=self.client.get('/api/session').json()['user']['settings']
        settings.update(leaderboard=False,public_profile=True)
        self.post('settings',settings)
        self.assertEqual(self.client.get('/api/leaderboard?game=memory').json()['players'],[])
        profile=self.client.get('/api/players/gavi').json()
        self.assertNotIn('email',profile)

    def test_snake_score_replay_and_ownership(self):
        self.register()
        r=self.post('runs/start',{'game':'snake'}).json()
        turns=[[1,0] for _ in range(18)]
        self.assertEqual(self.post('runs/'+r['id']+'/finish',{'turns':turns}).status_code,400)
        with self.app.state.db() as con:con.execute('UPDATE runs SET started=started-10 WHERE id=?',(r['id'],))
        res=self.post('runs/'+r['id']+'/finish',{'turns':turns})
        self.assertEqual(res.status_code,200,res.text)
        other=TestClient(self.app)
        self.register('nova@example.com','nova',other)
        self.assertEqual(self.post('runs/'+r['id']+'/finish',{},other).status_code,409)
        other.close()

    def test_trivia_checks_answers_server_side(self):
        self.register()
        r=self.post('runs/start',{'game':'trivia'}).json()
        self.assertNotIn('correct',r['questions'][0])
        self.assertEqual(self.post('runs/'+r['id']+'/finish',{}).status_code,400)
        for i in range(10):
            q=r['questions'][i]
            correct=QUESTIONS[i][1][0]
            ans=q['options'].index(correct)
            res=self.post('runs/'+r['id']+'/answer',{'index':i,'answer':ans})
            self.assertEqual(res.status_code,200,res.text)
        result=self.post('runs/'+r['id']+'/finish',{'score':0})
        self.assertEqual(result.json()['score'],10)

    def test_typing_timer_and_server_score(self):
        self.register()
        r=self.post('runs/start',{'game':'typing','duration':30}).json()
        self.assertEqual(self.post('runs/'+r['id']+'/finish',{'text':'hello'}).status_code,400)
        with self.app.state.db() as con:con.execute('UPDATE runs SET started=started-31 WHERE id=?',(r['id'],))
        text=r['passage'][:100]
        res=self.post('runs/'+r['id']+'/finish',{'text':text,'score':999})
        self.assertEqual(res.status_code,200,res.text)
        self.assertEqual(res.json()['score'],40)

    def test_local_ttt_saved_but_unranked(self):
        self.register()
        r=self.post('runs/start',{'game':'tic-tac-toe','mode':'local'}).json()
        res=self.post('runs/'+r['id']+'/finish',{'actions':[0,3,1,4,2]})
        self.assertEqual(res.status_code,200,res.text)
        self.assertFalse(res.json()['ranked'])

    def test_profile_email_change_and_delete_cascade(self):
        self.register()
        self.assertEqual(self.post('profile',{'display_name':'<script>','username':'gavi_new'}).status_code,200)
        self.assertEqual(self.post('change-email',{'email':'new@example.com','password':'wrong'}).status_code,400)
        self.post('change-email',{'email':'new@example.com','password':'long-password-123'})
        self.assertEqual(self.client.get('/api/session').json()['user']['email'],'gavi@example.com')
        self.assertEqual(self.post('verify',{'code':self.code()}).status_code,200)
        self.assertEqual(self.client.get('/api/session').json()['user']['email'],'new@example.com')
        self.assertEqual(self.post('delete-account',{'confirmation':'DELETE','password':'wrong'}).status_code,400)
        self.assertEqual(self.post('delete-account',{'confirmation':'DELETE','password':'long-password-123'}).status_code,200)
        with self.app.state.db() as con:
            self.assertEqual(con.execute('SELECT count(*) FROM users').fetchone()[0],0)
        self.assertIsNone(self.client.get('/api/session').json()['user'])

    def test_google_verified_token_and_state(self):
        from cryptography.hazmat.primitives.asymmetric import rsa
        from urllib.parse import urlparse, parse_qs
        import jwt
        import httpx
        self.app.state.config['GOOGLE_CLIENT_ID']='test-google-client'
        self.app.state.config['GOOGLE_CLIENT_SECRET']='test-google-secret'
        response=self.client.get('/auth/google',follow_redirects=False)
        params=parse_qs(urlparse(response.headers['location']).query)
        self.assertEqual(params['code_challenge_method'],['S256'])
        key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        claims={'sub':'google-test-subject','iss':'https://accounts.google.com','aud':'test-google-client',
                'iat':int(time.time()),'exp':int(time.time())+300,'nonce':params['nonce'][0],
                'email':'google@example.com','email_verified':True,'name':'Google Player'}
        token=jwt.encode(claims,key,algorithm='RS256',headers={'kid':'test'})
        fake_response=httpx.Response(200,json={'id_token':token},request=httpx.Request('POST','https://oauth2.googleapis.com/token'))
        with patch('app.httpx.post',return_value=fake_response), patch('app.jwt.PyJWKClient') as jwks:
            import types
            jwks.return_value.get_signing_key_from_jwt.return_value=types.SimpleNamespace(key=key.public_key())
            result=self.client.get('/auth/google/callback',params={'state':params['state'][0],'code':'test-code'},follow_redirects=False)
        self.assertEqual(result.status_code,303)
        self.assertEqual(result.headers['location'],'/dashboard')
        current=self.client.get('/api/session').json()['user']
        self.assertTrue(current['google_linked'])
        self.assertEqual(current['email'],'google@example.com')
        self.assertNotIn('google_sub',current)
        self.post('logout')
        self.client.get('/auth/google',follow_redirects=False)
        result=self.client.get('/auth/google/callback?state=invalid&code=test',follow_redirects=False)
        self.assertIn('expired',result.headers['location'])
        self.assertIsNone(self.client.get('/api/session').json()['user'])

    def test_google_disabled_and_html_routes(self):
        r=self.client.get('/auth/google',follow_redirects=False)
        self.assertEqual(r.status_code,303)
        for route in ['/login','/signup','/dashboard','/games','/profile','/settings','/leaderboard','/terms','/privacy']:
            res=self.client.get(route)
            self.assertEqual(res.status_code,200)
        self.assertEqual(self.client.get('/api/not-a-route').status_code,404)


from data import QUESTIONS
if __name__=='__main__':unittest.main()
