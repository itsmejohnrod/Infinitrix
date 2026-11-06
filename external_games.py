"""Third-party-backed rounds. No silent local-content fallback."""
import html,json,secrets,time
import httpx
from fastapi import HTTPException,Request

SOURCES={
 'sudoku':('Dosuku','https://sudoku-api.vercel.app/'),
 'memory':('Deck of Cards API','https://deckofcardsapi.com/'),
 'word':('Free Dictionary API','https://dictionaryapi.dev/'),
 'trivia':('Open Trivia DB','https://opentdb.com/'),
 'pokemon':('PokéAPI','https://pokeapi.co/')}
WORDS=['garden','planet','window','forest','silver','bridge','pencil','castle','ocean','music','river','winter','summer','flower','journey','puzzle']

def fetch(url,params=None):
 try:
  r=httpx.get(url,params=params,timeout=18,follow_redirects=True);r.raise_for_status();return r.json()
 except Exception:
  raise HTTPException(503,'The game provider is unavailable. Please try again. No local replacement round was started.')

def shuffled(items):
 items=list(items);secrets.SystemRandom().shuffle(items);return items

def install(app,db,user,rate):
 def load(con,rid,uid):
  r=con.execute('SELECT * FROM runs WHERE id=? AND user_id=? AND finished=0',(rid,uid)).fetchone()
  if not r or time.time()-r['started']>7200:raise HTTPException(409,'Round ended or expired. Start another round.')
  p=json.loads(r['payload'])
  if not p.get('external'):raise HTTPException(400,'Not an external API round.')
  return r,p
 def visible(rid,g,p):
  out={'id':rid,'game':g,'source':SOURCES[g][0],'source_url':SOURCES[g][1]}
  if g=='memory':out.update(revealed=p['revealed'],matched=p['matched'],moves=p['moves'])
  elif g=='sudoku':out.update(board=p['board'],difficulty=p['difficulty'])
  else:
   q=p['questions'][p['index']]
   out.update(question=q['question'],options=q['options'],image=q.get('image'),index=p['index'],total=len(p['questions']),correct=p['correct'],answered=p['answered'])
  return out
 @app.post('/api/external/start')
 def start(request:Request,data:dict):
  u=user(request);rate(request,'external-start',30,600);g=data.get('game')
  if g not in SOURCES:raise HTTPException(400,'Choose a game.')
  p={'external':True,'source':SOURCES[g][0]}
  if g=='memory':
   d=fetch('https://deckofcardsapi.com/api/deck/new/draw/',{'count':6})
   cards=d.get('cards',[])
   if not d.get('success') or len(cards)!=6:raise HTTPException(503,'Card provider returned an incomplete deck.')
   p.update(cards=shuffled([c['code'] for c in cards]*2),revealed=[],matched=[],moves=0)
  elif g=='sudoku':
   d=fetch('https://sudoku-api.vercel.app/api/dosuku')
   try:
    grid=d['newboard']['grids'][0];board=grid['value'];solution=grid['solution']
    assert len(board)==9 and len(solution)==9 and all(len(row)==9 for row in board+solution)
    assert all(type(v)is int and 0<=v<=9 for row in board for v in row)
    assert all(set(row)==set(range(1,10)) for row in solution)
    assert all(set(solution[y][x] for y in range(9))==set(range(1,10)) for x in range(9))
    assert all(set(solution[y][x] for y in range(by,by+3) for x in range(bx,bx+3))==set(range(1,10)) for by in [0,3,6] for bx in [0,3,6])
    assert all(board[y][x] in [0,solution[y][x]] for y in range(9) for x in range(9))
   except Exception:raise HTTPException(503,'Sudoku provider returned an invalid puzzle.')
   p.update(board=board,solution=solution,difficulty=str(grid.get('difficulty','Standard')))
  else:
   questions=[]
   if g=='trivia':
    d=fetch('https://opentdb.com/api.php',{'amount':10,'type':'multiple'})
    if d.get('response_code')!=0 or len(d.get('results',[]))!=10:raise HTTPException(503,'Trivia provider is busy. Wait a few seconds and try again.')
    for q in d['results']:
     answer=html.unescape(q['correct_answer']);options=shuffled([answer]+[html.unescape(x) for x in q['incorrect_answers']])
     questions.append({'question':html.unescape(q['question']),'options':options,'answer':options.index(answer)})
   elif g=='word':
    chosen=shuffled(WORDS)[:3]
    for word in chosen:
     d=fetch('https://api.dictionaryapi.dev/api/v2/entries/en/'+word)
     try:
      definition=next(x['definition'] for m in d[0]['meanings'] for x in m['definitions'] if word not in x['definition'].lower())
     except Exception:raise HTTPException(503,'Dictionary provider did not return a usable clue. Try another round.')
     options=shuffled([word]+shuffled([w for w in WORDS if w!=word])[:3])
     questions.append({'question':definition,'options':options,'answer':options.index(word)})
   else:
    ids=secrets.SystemRandom().sample(range(1,152),4)
    creatures=[fetch('https://pokeapi.co/api/v2/pokemon/'+str(i)) for i in ids]
    names=[c['name'] for c in creatures]
    for c in creatures[:3]:
     image=c.get('sprites',{}).get('front_default')
     if not image:raise HTTPException(503,'The Pokémon provider did not return a sprite.')
     options=shuffled(names)
     questions.append({'question':'Which Pokémon is shown?','image':image,'options':options,'answer':options.index(c['name'])})
   p.update(questions=questions,index=0,correct=0,answered=False)
  rid=secrets.token_urlsafe(24)
  with db() as con:
   con.execute('UPDATE runs SET finished=1 WHERE user_id=? AND game=? AND finished=0',(u['id'],g))
   con.execute('INSERT INTO runs VALUES(?,?,?,?,?,0)',(rid,u['id'],g,time.time(),json.dumps(p)))
  return visible(rid,g,p)
 @app.post('/api/external/{rid}/action')
 def action(rid:str,request:Request,data:dict):
  u=user(request)
  with db() as con:
   con.execute('BEGIN IMMEDIATE');r,p=load(con,rid,u['id']);g=r['game'];done=False;feedback=None;score=0
   if g=='memory':
    if data.get('action')=='continue':p['revealed']=[]
    else:
     i=data.get('index')
     if type(i)is not int or not 0<=i<12 or i in p['matched'] or i in p['revealed'] or len(p['revealed'])==2:raise HTTPException(400,'Choose another tile or press Continue.')
     p['revealed'].append(i)
     if len(p['revealed'])==2:
      p['moves']+=1;a,b=p['revealed']
      if p['cards'][a]==p['cards'][b]:p['matched']+=p['revealed'];p['revealed']=[]
     done=len(p['matched'])==12;score=p['moves']
    out=visible(rid,g,p)
    out['tiles']={str(i):p['cards'][i] for i in p['matched']+p['revealed']}
   elif g=='sudoku':
    board=data.get('board')
    if not isinstance(board,list) or board!=p['solution']:raise HTTPException(400,'Some cells are incomplete or incorrect. Keep trying.')
    done=True;score=max(1,round(time.time()-r['started']));out=visible(rid,g,p)
   else:
    if data.get('action')=='next':
     if not p['answered']:raise HTTPException(400,'Choose an answer first.')
     if p['index']==len(p['questions'])-1:done=True
     else:p['index']+=1;p['answered']=False
    else:
     i=data.get('answer');q=p['questions'][p['index']]
     if p['answered'] or type(i)is not int or not 0<=i<len(q['options']):raise HTTPException(400,'Answer this question once.')
     correct=i==q['answer'];p['correct']+=int(correct);p['answered']=True
     feedback='Correct.' if correct else 'Answer: '+q['options'][q['answer']]
    score=p['correct'];out=visible(rid,g,p)
   if done:
    detail={'source':p['source'],'seconds':round(time.time()-r['started'],1),'external':True}
    if g not in ['memory','sudoku']:detail['total']=len(p['questions'])
    con.execute('INSERT INTO results(run_id,user_id,game,score,detail,ranked,created_at) VALUES(?,?,?,?,?,1,?)',(rid,u['id'],g,score,json.dumps(detail),time.time()))
    con.execute('UPDATE runs SET finished=1 WHERE id=?',(rid,))
   else:con.execute('UPDATE runs SET payload=? WHERE id=?',(json.dumps(p),rid))
  return {**out,'done':done,'score':score,'feedback':feedback}
