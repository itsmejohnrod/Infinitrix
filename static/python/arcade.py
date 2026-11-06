"""PyScript interface for five third-party-backed games."""
import asyncio,json
from pyscript import document,window
from pyscript.ffi import create_proxy
names={'sudoku':'Sudoku','memory':'Card Memory','word':'Word Detective','trivia':'Trivia Challenge','pokemon':'Guess the Pokémon'}
game='sudoku'
round_data=None
version=0
busy=False
proxies=[]

def el(id):return document.getElementById(id)
def escape(s):return str(s).replace('&','&amp;').replace('<','&lt;').replace('>','&gt;').replace('"','&quot;')
def message(s):
 if el('game-message') is not None:el('game-message').textContent=str(s)
def leave():
 global version,round_data,busy
 version+=1;round_data=None;busy=False

def select(key):
 global game
 leave();game=str(key)
 if el('playfield') is None:return
 el('game-start').textContent='Play '+names[game];el('game-start').disabled=False
 el('game-pause').hidden=True;el('game-option').hidden=True
 el('game-score').textContent='Ready'
 el('game-instructions').textContent='New rounds require the external provider. Your account stays in Infinitrix.'
 el('playfield').innerHTML='<p class="eyebrow">External API game</p><h3>'+escape(names[game])+'</h3><p class="muted">Press Play to request a new round. Provider errors will be shown here.</p>'
 message('No external content has been requested yet.')

async def request(path,data):return json.loads(str(await window.gameAPI(path,json.dumps(data))))

def draw(d):
 field=el('playfield')
 if field is None:return
 source='<p class="hint">Live round from <a target="_blank" rel="noopener" href="'+escape(d['source_url'])+'">'+escape(d['source'])+'</a></p>'
 if d['game']=='memory':
  tiles=d.get('tiles',{});markup='<div class="memory-board">'
  for i in range(12):
   val=tiles.get(str(i));matched=i in d['matched']
   markup+='<button class="memory-card '+('matched' if matched else 'revealed' if val else '')+'" data-ext-tile="'+str(i)+'" '+('disabled' if matched else '')+' aria-label="Tile '+str(i+1)+(', '+escape(val) if val else ', hidden')+'">'+(escape(val) if val else str(i+1))+'</button>'
  markup+='</div>'
  if len(d['revealed'])==2:markup+='<button id="ext-next" style="margin-top:16px">Continue</button>'
  el('game-score').textContent='Moves: '+str(d['moves']);field.innerHTML=source+markup
 elif d['game']=='sudoku':
  # Preserve player input when re-rendering is unnecessary; submit errors keep the board.
  markup='<div class="sudoku-grid" aria-label="Sudoku puzzle">'
  for y,row in enumerate(d['board']):
   for x,v in enumerate(row):
    markup+='<input aria-label="Row '+str(y+1)+' column '+str(x+1)+'" data-cell="'+str(y*9+x)+'" inputmode="numeric" pattern="[1-9]" maxlength="1" value="'+(str(v) if v else '')+'" '+('readonly' if v else '')+'>'
  field.innerHTML=source+markup+'</div><button id="ext-check" style="margin-top:16px">Check completed board</button>'
  el('game-score').textContent='Difficulty: '+str(d['difficulty'])
 else:
  markup=source
  if d.get('image'):markup+='<img class="pokemon-sprite" src="'+escape(d['image'])+'" alt="Pokémon to identify" onerror="this.alt=\'Image unavailable; restart this round\'">'
  markup+='<p class="quiz-question">'+escape(d['question'])+'</p><div class="quiz-options">'
  for i,o in enumerate(d['options']):markup+='<button data-ext-answer="'+str(i)+'" '+('disabled' if d['answered'] else '')+'>'+escape(o)+'</button>'
  markup+='</div>'
  if d['answered']:markup+='<button id="ext-next" style="margin-top:16px">'+('Finish round' if d['index']==d['total']-1 else 'Next question')+'</button>'
  field.innerHTML=markup;el('game-score').textContent=str(d['index']+1)+' of '+str(d['total'])+' / Correct: '+str(d['correct'])
 if d.get('feedback'):message(d['feedback'])
 if d.get('done'):
  field.innerHTML=source+'<h3>Round complete.</h3><p>Your result has been saved.</p>'
  el('game-score').textContent='Final result: '+str(d['score']);message('Result saved. Play again whenever you are ready.')
  el('game-start').textContent='Play again'
  window.gameSound();asyncio.ensure_future(refresh_stats())

async def refresh_stats():
 await window.gameSaved()

async def perform(start=False,data=None):
 global round_data,busy,version
 if busy:return
 if not start and (round_data is None or round_data.get('done')):return
 busy=True
 if start:version+=1
 v=version
 el('game-start').disabled=True
 message('Contacting the provider.' if start else 'Checking your move.')
 try:
  result=await request('external/start' if start else 'external/'+round_data['id']+'/action',{'game':game} if start else data)
  if v!=version:return
  round_data=result;draw(result)
  if start:window.gameStarted();message('Round ready. Source: '+result['source']);el('game-start').textContent='Restart'
 except Exception as error:
  if v==version:message(str(error))
 finally:
  if v==version:
   busy=False
   if el('game-start') is not None:el('game-start').disabled=False

def click(event):
 target=event.target.closest('button')
 if target is None:return
 id=str(target.id)
 if id=='game-start':asyncio.ensure_future(perform(True))
 elif target.hasAttribute('data-ext-tile'):asyncio.ensure_future(perform(data={'index':int(target.getAttribute('data-ext-tile'))}))
 elif target.hasAttribute('data-ext-answer'):asyncio.ensure_future(perform(data={'answer':int(target.getAttribute('data-ext-answer'))}))
 elif id=='ext-next':asyncio.ensure_future(perform(data={'action':'continue' if game=='memory' else 'next'}))
 elif id=='ext-check':
  values=[]
  for cell in document.querySelectorAll('[data-cell]'):
   try:values.append(int(str(cell.value)))
   except Exception:message('Fill all cells with numbers from 1 to 9.');return
  asyncio.ensure_future(perform(data={'board':[values[y*9:y*9+9] for y in range(9)]}))

def proxy(f):
 p=create_proxy(f);proxies.append(p);return p
window.arcadeSelect=proxy(select);window.arcadeLeave=proxy(leave)
document.addEventListener('click',proxy(click))
window.pythonArcadeReady()
