"""Infinitrix API and local web server. Run: python app.py"""
import hashlib
import hmac
import html
import json
import logging
import os
from pathlib import Path
import re
import secrets
import smtplib
import sqlite3
import ssl
import time
from datetime import datetime, timezone
from contextlib import contextmanager
from email.message import EmailMessage
from urllib.parse import urlencode

import httpx
import jwt
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from data import DEFAULT_SETTINGS, GAMES, PASSAGES, QUESTIONS
from game_models import Memory, Random, Snake, computer_move, typing_result, winner

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / '.env')
log = logging.getLogger('infinitrix')
PBKDF_ROUNDS = 600_000


def password_hash(password):
    salt = secrets.token_bytes(16)
    result = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, PBKDF_ROUNDS)
    return f'pbkdf2_sha256${PBKDF_ROUNDS}${salt.hex()}${result.hex()}'


def password_matches(password, encoded):
    try:
        _, rounds, salt, expected = encoded.split('$')
        result = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), int(rounds))
        return hmac.compare_digest(result.hex(), expected)
    except (ValueError, AttributeError):
        return False


def create_app(overrides=None):
    config = {
        'APP_ENV': os.getenv('APP_ENV', 'development'),
        'BASE_URL': os.getenv('BASE_URL', 'http://localhost:8000').rstrip('/'),
        'DATABASE_PATH': os.getenv('DATABASE_PATH', str(ROOT / 'instance/infinitrix.sqlite3')),
        'SECRET_KEY': os.getenv('SECRET_KEY', ''),
        'MAIL_MODE': os.getenv('MAIL_MODE', 'console'),
        'GOOGLE_CLIENT_ID': os.getenv('GOOGLE_CLIENT_ID', ''),
        'GOOGLE_CLIENT_SECRET': os.getenv('GOOGLE_CLIENT_SECRET', ''),
        'TRIVIA_API_ENABLED': os.getenv('TRIVIA_API_ENABLED', 'true').lower() == 'true',
    }
    config.update(overrides or {})
    production = config['APP_ENV'] == 'production'
    if production and (len(config['SECRET_KEY']) < 32 or config['MAIL_MODE'] != 'smtp' or not config['BASE_URL'].startswith('https://')):
        raise RuntimeError('Production requires SECRET_KEY (32+ characters), MAIL_MODE=smtp, and an HTTPS BASE_URL.')
    dbpath = Path(config['DATABASE_PATH'])
    if not dbpath.is_absolute():
        dbpath = ROOT / dbpath
    dbpath.parent.mkdir(parents=True, exist_ok=True)
    if not config['SECRET_KEY']:
        keypath = dbpath.parent / '.local-secret'
        if not keypath.exists():
            keypath.write_text(secrets.token_hex(32))
            keypath.chmod(0o600)
        config['SECRET_KEY'] = keypath.read_text().strip()
    app = FastAPI(title='Infinitrix API', docs_url=None, redoc_url=None, openapi_url=None)
    app.state.config = config

    @contextmanager
    def db():
        con = sqlite3.connect(str(dbpath), timeout=10)
        con.row_factory = sqlite3.Row
        con.execute('PRAGMA foreign_keys=ON')
        try:
            with con:
                yield con
        finally:
            con.close()

    app.state.db = db
    with db() as con:
        con.executescript('''
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS users (
          id INTEGER PRIMARY KEY, email TEXT UNIQUE NOT NULL, username TEXT UNIQUE NOT NULL,
          display_name TEXT NOT NULL, password TEXT, google_sub TEXT UNIQUE,
          verified INTEGER NOT NULL DEFAULT 0, created_at REAL NOT NULL,
          settings TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1);
        CREATE TABLE IF NOT EXISTS sessions (
          token TEXT PRIMARY KEY, user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
          csrf TEXT NOT NULL, data TEXT NOT NULL, expires REAL NOT NULL, version INTEGER);
        CREATE TABLE IF NOT EXISTS challenges (
          id TEXT PRIMARY KEY, user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
          email TEXT NOT NULL, purpose TEXT NOT NULL, code_hash TEXT NOT NULL,
          expires REAL NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, sent REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS runs (
          id TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          game TEXT NOT NULL, started REAL NOT NULL, payload TEXT NOT NULL, finished INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS results (
          id INTEGER PRIMARY KEY, run_id TEXT UNIQUE REFERENCES runs(id) ON DELETE CASCADE,
          user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          game TEXT NOT NULL, score REAL NOT NULL, detail TEXT NOT NULL, ranked INTEGER NOT NULL,
          created_at REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS limits (bucket TEXT, created_at REAL);
        CREATE INDEX IF NOT EXISTS limits_bucket ON limits(bucket,created_at);
        CREATE INDEX IF NOT EXISTS results_game ON results(game,created_at);
        ''')

    def digest(value):
        return hmac.new(config['SECRET_KEY'].encode(), value.encode(), hashlib.sha256).hexdigest()

    def persist(request):
        s = request.state.session
        with db() as con:
            con.execute('UPDATE sessions SET data=?, user_id=?, version=? WHERE token=?',
                        (json.dumps(s['data']), s['user_id'], s['version'], s['token']))

    def rotate(request, uid=None, version=None):
        old = getattr(request.state, 'session', None)
        raw = secrets.token_urlsafe(32)
        s = {'token': digest(raw), 'csrf': secrets.token_urlsafe(24), 'data': {},
             'user_id': uid, 'version': version, 'expires': time.time() + 8 * 3600}
        with db() as con:
            con.execute('DELETE FROM sessions WHERE expires<?', (time.time(),))
            con.execute('DELETE FROM challenges WHERE expires<?', (time.time()-86400,))
            if old:
                con.execute('DELETE FROM sessions WHERE token=?', (old['token'],))
            con.execute('INSERT INTO sessions VALUES(?,?,?,?,?,?)',
                        (s['token'], uid, s['csrf'], '{}', s['expires'], version))
        request.state.session = s
        request.state.cookie = raw
        return s

    def user(request):
        s = request.state.session
        with db() as con:
            u = con.execute('SELECT * FROM users WHERE id=?', (s['user_id'],)).fetchone()
        if not u or not u['verified'] or u['version'] != s['version']:
            raise HTTPException(401, 'Please log in to continue.')
        return dict(u)

    def rate(request, action, maximum=10, period=600):
        address = request.client.host if request.client else 'unknown'
        bucket = digest(action + ':' + address)
        now = time.time()
        with db() as con:
            con.execute('DELETE FROM limits WHERE created_at<?', (now - 3600,))
            count = con.execute('SELECT count(*) FROM limits WHERE bucket=? AND created_at>?', (bucket, now - period)).fetchone()[0]
            if count >= maximum:
                raise HTTPException(429, 'Too many attempts. Please wait and try again.')
            con.execute('INSERT INTO limits VALUES(?,?)', (bucket, now))

    def send_mail(email, code, purpose):
        subject = {'signup': 'Verify your Infinitrix account', 'reset': 'Reset your Infinitrix password', 'email': 'Verify your new email address'}[purpose]
        body = f'{subject}\n\nYour verification code is {code}.\nIt expires in 10 minutes.\nIf you did not request this, ignore this message.\n'
        if config['MAIL_MODE'] == 'console' and not production:
            mailbox = dbpath.parent / 'mailbox.log'
            with mailbox.open('a', encoding='utf-8') as f:
                f.write(f'\nLOCAL DEVELOPMENT ONLY | {email}\n{body}')
            mailbox.chmod(0o600)
            print(f'[Local mail] Code written to {mailbox}. No email was sent.')
            return
        if config['MAIL_MODE'] != 'smtp':
            raise HTTPException(503, 'Email delivery is not configured.')
        msg = EmailMessage()
        msg['Subject'], msg['From'], msg['To'] = subject, os.getenv('SMTP_FROM', ''), email
        msg.set_content(body)
        try:
            host, port = os.getenv('SMTP_HOST', ''), int(os.getenv('SMTP_PORT', '587'))
            if os.getenv('SMTP_SECURITY', 'starttls') == 'ssl':
                conn = smtplib.SMTP_SSL(host, port, timeout=15, context=ssl.create_default_context())
            else:
                conn = smtplib.SMTP(host, port, timeout=15)
                conn.starttls(context=ssl.create_default_context())
            with conn:
                conn.login(os.getenv('SMTP_USERNAME', ''), os.getenv('SMTP_PASSWORD', ''))
                conn.send_message(msg)
        except Exception:
            log.exception('Email delivery failed')
            raise HTTPException(503, 'We could not send the code. Please try again shortly.')

    def new_challenge(request, uid, email, purpose):
        now, cid, code = time.time(), secrets.token_urlsafe(24), f'{secrets.randbelow(1_000_000):06d}'
        # Send first so a failed delivery does not consume a previous working code.
        send_mail(email, code, purpose)
        with db() as con:
            con.execute('DELETE FROM challenges WHERE user_id=? AND purpose=?', (uid, purpose))
            con.execute('INSERT INTO challenges VALUES(?,?,?,?,?,?,0,?)',
                        (cid, uid, email, purpose, digest(cid + ':' + code), now + 600, now))
        request.state.session['data']['challenge'] = cid
        persist(request)

    def checked_email(value):
        value = str(value).strip().lower()
        if len(value) > 254 or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', value):
            raise HTTPException(400, 'Enter a valid email address.')
        return value

    def checked_password(value):
        if not isinstance(value, str) or not 12 <= len(value) <= 128:
            raise HTTPException(400, 'Use a password between 12 and 128 characters.')
        return value

    def identity(data):
        name, handle = str(data.get('display_name', '')).strip(), str(data.get('username', '')).strip().lower()
        if not 1 <= len(name) <= 50:
            raise HTTPException(400, 'Display names must contain 1 to 50 characters.')
        if not re.fullmatch(r'[a-z0-9_]{3,24}', handle):
            raise HTTPException(400, 'Use 3 to 24 lowercase letters, numbers, or underscores for your username.')
        return name, handle

    def public_user(u):
        return {k: u[k] for k in ['id','email','username','display_name','verified','created_at']} | {
            'settings': json.loads(u['settings']), 'google_linked': bool(u['google_sub']), 'has_password': bool(u['password'])}

    @app.middleware('http')
    async def security(request, call_next):
        is_api = request.url.path.startswith(('/api/', '/auth/'))
        request.state.cookie = None
        if is_api:
            raw = request.cookies.get('infinitrix', '')
            with db() as con:
                row = con.execute('SELECT * FROM sessions WHERE token=? AND expires>?', (digest(raw), time.time())).fetchone() if raw else None
            if row:
                request.state.session = dict(row)
                request.state.session['data'] = json.loads(row['data'])
            else:
                rotate(request)
            if request.method in ['POST', 'PUT', 'DELETE', 'PATCH']:
                token = request.headers.get('X-CSRF-Token', '')
                if not hmac.compare_digest(token, request.state.session['csrf']):
                    return JSONResponse({'detail': 'Your session changed. Refresh the page and try again.'}, 403)
                if int(request.headers.get('content-length', '0') or '0') > 256_000:
                    return JSONResponse({'detail': 'Request too large.'}, 413)
        response = await call_next(request)
        if request.state.cookie:
            response.set_cookie('infinitrix', request.state.cookie, httponly=True, secure=production,
                                samesite='lax', max_age=8 * 3600, path='/')
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        vendor = request.url.path.startswith('/static/vendor/')
        response.headers['X-Frame-Options'] = 'SAMEORIGIN' if vendor else 'DENY'
        if vendor:
            response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self' https://cdn.jsdelivr.net; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; media-src 'self' blob:; font-src 'self' data:; connect-src 'self' https://cdn.jsdelivr.net; object-src 'none'; frame-src 'none'; frame-ancestors 'self'; base-uri 'none'; form-action 'none'"
        response.headers['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=()'
        if is_api:
            response.headers['Cache-Control'] = 'no-store'
        if production:
            response.headers['Strict-Transport-Security'] = 'max-age=31536000'
        return response

    @app.get('/api/session')
    def session_info(request: Request):
        try:
            u = public_user(user(request))
        except HTTPException:
            u = None
        pending = None
        cid = request.state.session['data'].get('challenge')
        if cid:
            with db() as con:
                c = con.execute('SELECT email,purpose FROM challenges WHERE id=?', (cid,)).fetchone()
            if c:
                local, domain = c['email'].split('@', 1)
                pending = {'email': local[:2] + '***@' + domain, 'purpose': c['purpose']}
        return {'user': u, 'csrf': request.state.session['csrf'], 'pending': pending,
                'google_enabled': bool(config['GOOGLE_CLIENT_ID'] and config['GOOGLE_CLIENT_SECRET']),
                'local_mail': config['MAIL_MODE'] == 'console', 'games': GAMES}

    @app.post('/api/signup')
    def signup(request: Request, data: dict):
        rate(request, 'signup', 6)
        name, handle = identity(data)
        email, password = checked_email(data.get('email')), checked_password(data.get('password'))
        with db() as con:
            existing = con.execute('SELECT * FROM users WHERE email=? OR username=?', (email, handle)).fetchone()
            if existing:
                if existing['email'] == email and not existing['verified'] and password_matches(password, existing['password']):
                    uid = existing['id']
                else:
                    raise HTTPException(409, 'That email or username is already in use. Log in or choose another.')
            else:
                uid = con.execute('INSERT INTO users(email,username,display_name,password,created_at,settings) VALUES(?,?,?,?,?,?)',
                        (email, handle, name, password_hash(password), time.time(), json.dumps(DEFAULT_SETTINGS))).lastrowid
        new_challenge(request, uid, email, 'signup')
        return {'next': '/verify'}

    @app.post('/api/login')
    def login(request: Request, data: dict):
        rate(request, 'login', 20)
        email = str(data.get('email','')).lower().strip()
        pw = str(data.get('password',''))[:129]
        with db() as con:
            u = con.execute('SELECT * FROM users WHERE email=?', (email,)).fetchone()
        valid = password_matches(pw, u['password'] if u else password_hash('dummy-password-value'))
        if not u or not valid:
            raise HTTPException(401, 'Email or password is incorrect.')
        if not u['verified']:
            new_challenge(request, u['id'], email, 'signup')
            return {'next': '/verify'}
        rotate(request, u['id'], u['version'])
        return {'next': '/dashboard'}

    @app.post('/api/logout')
    def logout(request: Request):
        rotate(request)
        return {'next': '/login'}

    @app.post('/api/forgot')
    def forgot(request: Request, data: dict):
        rate(request, 'recovery', 5)
        email = checked_email(data.get('email'))
        with db() as con:
            u = con.execute('SELECT * FROM users WHERE email=? AND verified=1', (email,)).fetchone()
        if u:
            new_challenge(request, u['id'], email, 'reset')
        else:
            # Same pending UI for unknown accounts; do not send mail or create a user.
            cid = secrets.token_urlsafe(24)
            with db() as con:
                con.execute('INSERT INTO challenges VALUES(?,NULL,?,?,?,?,0,?)', (cid,email,'reset',digest(cid),time.time()+600,time.time()))
            request.state.session['data']['challenge'] = cid
            persist(request)
        return {'next': '/verify'}

    @app.post('/api/resend')
    def resend(request: Request):
        rate(request, 'resend', 5)
        cid = request.state.session['data'].get('challenge','')
        with db() as con:
            c = con.execute('SELECT * FROM challenges WHERE id=?', (cid,)).fetchone()
        if not c:
            raise HTTPException(400, 'Start registration or password recovery first.')
        if time.time() - c['sent'] < 60:
            raise HTTPException(429, 'Wait 60 seconds before requesting another code.')
        if c['user_id']:
            new_challenge(request, c['user_id'], c['email'], c['purpose'])
        return {'message': 'If eligible, a new code has been sent.'}

    @app.post('/api/verify')
    def verify(request: Request, data: dict):
        rate(request, 'verify', 25)
        cid = request.state.session['data'].get('challenge','')
        with db() as con:
            con.execute('BEGIN IMMEDIATE')
            c = con.execute('SELECT * FROM challenges WHERE id=?', (cid,)).fetchone()
            valid = c and c['user_id'] and c['expires'] > time.time() and c['attempts'] < 5
            correct = valid and hmac.compare_digest(c['code_hash'], digest(cid + ':' + str(data.get('code',''))))
            if not correct:
                if c:
                    con.execute('UPDATE challenges SET attempts=attempts+1 WHERE id=?', (cid,))
                con.commit()
                raise HTTPException(400, 'Code is incorrect, expired, or locked. Request a new code if needed.')
            con.execute('DELETE FROM challenges WHERE id=?', (cid,))
            if c['purpose'] == 'signup':
                con.execute('UPDATE users SET verified=1 WHERE id=?', (c['user_id'],))
            elif c['purpose'] == 'email':
                try:
                    con.execute('UPDATE users SET email=?, version=version+1 WHERE id=?', (c['email'],c['user_id']))
                except sqlite3.IntegrityError:
                    raise HTTPException(409, 'This email address is already in use.')
            u = con.execute('SELECT * FROM users WHERE id=?', (c['user_id'],)).fetchone()
        if c['purpose'] == 'reset':
            rotate(request)
            request.state.session['data']['reset_uid'] = u['id']
            request.state.session['data']['reset_until'] = time.time() + 600
            persist(request)
            return {'next': '/reset-password'}
        rotate(request, u['id'], u['version'])
        return {'next': '/dashboard' if c['purpose'] == 'signup' else '/settings'}

    @app.post('/api/reset-password')
    def reset_password(request: Request, data: dict):
        s = request.state.session['data']
        if not s.get('reset_uid') or s.get('reset_until',0) < time.time():
            raise HTTPException(403, 'Verify a recovery code before resetting your password.')
        password = checked_password(data.get('password'))
        with db() as con:
            con.execute('UPDATE users SET password=?,version=version+1 WHERE id=?', (password_hash(password),s['reset_uid']))
            con.execute('DELETE FROM sessions WHERE user_id=?', (s['reset_uid'],))
        rotate(request)
        return {'next': '/login', 'message': 'Password updated. Log in with your new password.'}

    @app.post('/api/change-password')
    def change_password(request: Request, data: dict):
        rate(request, 'change-password', 6)
        u = user(request)
        if not u['password'] or not password_matches(str(data.get('current_password','')),u['password']):
            raise HTTPException(400, 'Current password is incorrect. Google-only accounts can use password recovery to set a password.')
        pw = checked_password(data.get('password'))
        with db() as con:
            con.execute('UPDATE users SET password=?,version=version+1 WHERE id=?', (password_hash(pw),u['id']))
            con.execute('DELETE FROM sessions WHERE user_id=?', (u['id'],))
        rotate(request, u['id'],u['version']+1)
        return {'message': 'Password changed. Other sessions have been signed out.'}

    @app.post('/api/change-email')
    def change_email(request: Request, data: dict):
        rate(request, 'change-email', 5)
        u = user(request)
        if not u['password'] or not password_matches(str(data.get('password','')), u['password']):
            raise HTTPException(400, 'Enter your current password. Google-only accounts must set a password through recovery first.')
        email = checked_email(data.get('email'))
        with db() as con:
            if con.execute('SELECT id FROM users WHERE email=?', (email,)).fetchone():
                raise HTTPException(409, 'This email address is already in use.')
        new_challenge(request,u['id'],email,'email')
        return {'next':'/verify'}

    @app.post('/api/profile')
    def profile_update(request: Request, data: dict):
        u = user(request)
        name, handle = identity(data)
        with db() as con:
            try:
                con.execute('UPDATE users SET display_name=?,username=? WHERE id=?', (name,handle,u['id']))
            except sqlite3.IntegrityError:
                raise HTTPException(409, 'This username is already taken.')
        return {'message':'Profile updated.'}

    @app.post('/api/settings')
    def settings_update(request: Request, data: dict):
        u = user(request)
        if data.get('text_size') not in ['standard','large']:
            raise HTTPException(400,'Choose a valid text size.')
        for k in ['reduced_motion','visual_effects','sound','public_profile','leaderboard']:
            if type(data.get(k)) is not bool:
                raise HTTPException(400,'Invalid preference value.')
        if type(data.get('volume')) is not int or not 0 <= data['volume'] <= 100:
            raise HTTPException(400,'Volume must be between 0 and 100.')
        settings = {k:data[k] for k in DEFAULT_SETTINGS}
        with db() as con:
            con.execute('UPDATE users SET settings=? WHERE id=?', (json.dumps(settings),u['id']))
        return {'message':'Preferences saved.'}

    @app.post('/api/delete-account')
    def delete_account(request: Request, data: dict):
        rate(request,'delete-account',5)
        u = user(request)
        if data.get('confirmation') != 'DELETE':
            raise HTTPException(400,'Type DELETE to confirm.')
        if u['password']:
            if not password_matches(str(data.get('password','')),u['password']):
                raise HTTPException(400,'Your password is incorrect.')
        else:
            if request.state.session['data'].get('google_reauth',0) < time.time()-300:
                raise HTTPException(403,'Use Link / verify Google in Settings first, then confirm deletion within five minutes.')
        with db() as con:
            con.execute('DELETE FROM users WHERE id=?',(u['id'],))
        rotate(request)
        return {'next':'/signup','message':'Your account and saved results have been deleted.'}

    @app.get('/auth/google')
    def google_start(request: Request, link: bool = False):
        if not config['GOOGLE_CLIENT_ID'] or not config['GOOGLE_CLIENT_SECRET']:
            return RedirectResponse('/login?notice=Google+sign-in+needs+configuration.+Use+email+for+now.',303)
        uid = user(request)['id'] if link else None
        s = request.state.session['data']
        s['oauth'] = {'state':secrets.token_urlsafe(24),'nonce':secrets.token_urlsafe(24),
                      'verifier':secrets.token_urlsafe(48),'until':time.time()+600,'link_uid':uid}
        persist(request)
        o = s['oauth']
        import base64
        challenge = base64.urlsafe_b64encode(hashlib.sha256(o['verifier'].encode()).digest()).rstrip(b'=').decode()
        params = {'client_id':config['GOOGLE_CLIENT_ID'],'redirect_uri':config['BASE_URL']+'/auth/google/callback',
                  'response_type':'code','scope':'openid email profile','state':o['state'],'nonce':o['nonce'],
                  'code_challenge':challenge,'code_challenge_method':'S256','prompt':'select_account'}
        return RedirectResponse('https://accounts.google.com/o/oauth2/v2/auth?'+urlencode(params),303)

    @app.get('/auth/google/callback')
    def google_callback(request: Request, state: str = '', code: str = '', error: str = ''):
        o = request.state.session['data'].pop('oauth',{})
        persist(request)
        def fail(message):
            return RedirectResponse('/login?'+urlencode({'notice':message}),303)
        if error or not code:
            return fail('Google sign-in was cancelled. You can try again.')
        if not o or o['until'] < time.time() or not hmac.compare_digest(state,o['state']):
            return fail('Google sign-in expired. Please start again.')
        try:
            res = httpx.post('https://oauth2.googleapis.com/token',data={
                'client_id':config['GOOGLE_CLIENT_ID'],'client_secret':config['GOOGLE_CLIENT_SECRET'],
                'code':code,'grant_type':'authorization_code','redirect_uri':config['BASE_URL']+'/auth/google/callback',
                'code_verifier':o['verifier']},timeout=15)
            res.raise_for_status()
            token = res.json()['id_token']
            signing = jwt.PyJWKClient('https://www.googleapis.com/oauth2/v3/certs').get_signing_key_from_jwt(token)
            claims = jwt.decode(token,signing.key,algorithms=['RS256'],audience=config['GOOGLE_CLIENT_ID'],
                                issuer=['https://accounts.google.com','accounts.google.com'],
                                options={'require':['exp','iat','iss','aud','sub','nonce']})
            if not hmac.compare_digest(claims['nonce'],o['nonce']) or claims.get('email_verified') is not True:
                return fail('Google did not verify this account. Use email sign-in.')
            email = checked_email(claims['email'])
            with db() as con:
                u = con.execute('SELECT * FROM users WHERE google_sub=?',(claims['sub'],)).fetchone()
                if o.get('link_uid'):
                    current = user(request)
                    if current['id'] != o['link_uid'] or current['email'] != email or (u and u['id'] != current['id']):
                        return fail('Use the Google account matching your existing account email to link it.')
                    con.execute('UPDATE users SET google_sub=? WHERE id=?',(claims['sub'],current['id']))
                    u = con.execute('SELECT * FROM users WHERE id=?',(current['id'],)).fetchone()
                elif not u:
                    if con.execute('SELECT id FROM users WHERE email=?',(email,)).fetchone():
                        return fail('This email already has an account. Log in with your password and link Google in Settings.')
                    handle = re.sub('[^a-z0-9_]','',email.split('@')[0])[:16] or 'player'
                    handle += '_' + secrets.token_hex(3)
                    uid = con.execute('INSERT INTO users(email,username,display_name,google_sub,verified,created_at,settings) VALUES(?,?,?,?,1,?,?)',
                         (email,handle,str(claims.get('name','Player'))[:50],claims['sub'],time.time(),json.dumps(DEFAULT_SETTINGS))).lastrowid
                    u = con.execute('SELECT * FROM users WHERE id=?',(uid,)).fetchone()
            rotate(request,u['id'],u['version'])
            request.state.session['data']['google_reauth'] = time.time()
            persist(request)
            return RedirectResponse('/settings' if o.get('link_uid') else '/dashboard',303)
        except Exception:
            log.exception('Google sign-in failed')
            return fail('Google sign-in could not be completed. Please try again.')

    def results_for(uid):
        with db() as con:
            return [dict(r) | {'detail':json.loads(r['detail'])} for r in con.execute('SELECT * FROM results WHERE user_id=? ORDER BY created_at DESC,id DESC',(uid,))]

    @app.get('/api/stats')
    def stats(request: Request):
        u = user(request)
        rows = [r for r in results_for(u['id']) if r['game'] in GAMES and r['detail'].get('external')]
        records, counts = {}, {}
        for r in rows:
            key = r['game']
            counts[key] = counts.get(key,0)+1
            if key == 'tic-tac-toe' and r['detail'].get('mode') == 'local':
                continue
            if key not in records or (r['score'] < records[key]['score'] if key in ['memory','sudoku'] else r['score'] > records[key]['score']):
                records[key] = r
        return {'results':rows[:30], 'records':records, 'counts':counts,'total':len(rows),
                'explored':len(counts),'favorite':max(counts,key=counts.get) if counts else None}

    @app.get('/api/leaderboard')
    def leaderboard(request: Request, game: str = 'snake', period: str = 'all'):
        current = user(request)
        if game not in GAMES or period not in ['all','week']:
            raise HTTPException(400,'Invalid leaderboard filter.')
        now = datetime.now(timezone.utc)
        week_start = datetime(now.year,now.month,now.day,tzinfo=timezone.utc).timestamp() - now.weekday()*86400
        after = week_start if period == 'week' else 0
        with db() as con:
            rows = con.execute('SELECT r.*,u.display_name,u.username,u.settings FROM results r JOIN users u ON u.id=r.user_id WHERE r.game=? AND r.created_at>=? AND r.ranked=1 ORDER BY r.created_at ASC,r.id ASC',(game,after)).fetchall()
        best = {}
        for r in rows:
            if not json.loads(r['detail']).get('external'):
                continue
            if not json.loads(r['settings']).get('leaderboard',True):
                continue
            old = best.get(r['user_id'])
            if old is None or (r['score'] < old['score'] if game in ['memory','sudoku'] else r['score'] > old['score']):
                best[r['user_id']] = r
        ordered = sorted(best.values(),key=lambda r:(r['score'] if game in ['memory','sudoku'] else -r['score'],r['created_at']))
        players = [{'rank':i+1,'username':r['username'],'display_name':r['display_name'],'score':r['score'],
                    'created_at':r['created_at'],'you':r['user_id']==current['id']} for i,r in enumerate(ordered)]
        return {'players':players[:100], 'total':len(players), 'position':next((p for p in players if p['you']),None)}

    @app.get('/api/players/{username}')
    def player_profile(request: Request, username: str):
        user(request)
        with db() as con:
            row = con.execute('SELECT * FROM users WHERE username=? AND verified=1',(username,)).fetchone()
        if not row or not json.loads(row['settings']).get('public_profile'):
            raise HTTPException(404,'This profile is private or unavailable.')
        return {'display_name':row['display_name'],'username':row['username'],'created_at':row['created_at']}

    from external_games import install
    install(app, db, user, rate)

    app.mount('/static',StaticFiles(directory=ROOT/'static'),name='static')

    @app.get('/{path:path}')
    def index(path: str):
        if path.startswith(('api/','auth/')):
            raise HTTPException(404,'Not found.')
        return FileResponse(ROOT/'index.html',headers={'Cache-Control':'no-cache'})

    return app


if __name__ == '__main__':
    import uvicorn
    application = create_app()
    mode = application.state.config['MAIL_MODE']
    print(f'Infinitrix: http://localhost:8000 | Email mode: {mode}')
    uvicorn.run(application,host='127.0.0.1',port=8000)
