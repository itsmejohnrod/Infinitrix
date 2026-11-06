"""Exercise the actual browser Python module using a small DOM/transport test double.
This does not replace testing PyScript's real browser runtime on the local machine.
"""
import asyncio
import importlib.util
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


class Element:
    def __init__(self):
        self.textContent=''
        self.innerHTML=''
        self.hidden=False
        self.disabled=False
        self.value='30'
        self.maxLength=0
        self.classList=types.SimpleNamespace(toggle=lambda *a:None,add=lambda *a:None)
    def focus(self):pass


class EngineTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.elements={}
        self.calls=[]
        self.clock=1000.0
        self.game=''
        async def transport(path,body):
            data=json.loads(body)
            self.calls.append((path,data))
            if path=='runs/start':
                self.game=data['game']
                out={'id':'run-1','seed':42,'mode':data.get('mode','computer')}
                if self.game=='typing':out.update(duration=data['duration'],passage='hello world '*100)
                if self.game=='trivia':out.update(questions=[{'question':'Question?','options':['A','B','C','D']}] * 10,source='Original')
                return json.dumps(out)
            if path.endswith('/answer'):
                return json.dumps({'correct':True,'correct_index':0})
            return json.dumps({'ranked':True,'score':10})
        async def saved():return None
        self.document=types.SimpleNamespace(getElementById=lambda key:self.elements.setdefault(key,Element()),querySelectorAll=lambda q:[],addEventListener=lambda *a:None,hidden=False)
        self.window=types.SimpleNamespace(gameAPI=transport,gameSaved=saved,gameStarted=lambda:None,gameSound=lambda:None,
            setInterval=lambda *a:1,clearInterval=lambda *a:None,pythonArcadeReady=lambda:None,performance=types.SimpleNamespace(now=lambda:self.clock))
        py=types.ModuleType('pyscript');py.document=self.document;py.window=self.window
        ffi=types.ModuleType('pyscript.ffi');ffi.create_proxy=lambda f:f
        self.patch=patch.dict(sys.modules,{'pyscript':py,'pyscript.ffi':ffi})
        self.patch.start()
        spec=importlib.util.spec_from_file_location('arcade_test',ROOT/'static/python/arcade.py')
        self.engine=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.engine)
        self.engine.canvas_markup=lambda:None
        self.engine.draw_snake=lambda:None

    def tearDown(self):self.patch.stop()

    async def test_memory_completes_and_sends_replay(self):
        e=self.engine;e.select_game('memory');await e.start_game()
        for card in range(6):
            for i,c in enumerate(e.model.cards):
                if c==card:e.choose_memory(i)
        await asyncio.sleep(0)
        self.assertFalse(e.active)
        self.assertEqual(len(self.calls[-1][1]['actions']),12)
        self.assertIn('saved',self.elements['game-message'].textContent)

    async def test_local_ttt_finish_and_navigation_cleanup(self):
        e=self.engine;e.select_game('tic-tac-toe')
        self.elements['game-option'].value='local'
        await e.start_game()
        for i in [0,3,1,4,2]:e.choose_square(i)
        await asyncio.sleep(0)
        self.assertEqual(self.calls[-1][1]['actions'],[0,3,1,4,2])
        e.leave();self.assertIsNone(e.run)

    async def test_typing_ends_after_duration(self):
        e=self.engine;e.select_game('typing');await e.start_game()
        self.elements['typing-input']=Element();self.elements['typing-input'].value='hello'
        self.clock+=31000
        e.typing_tick();await asyncio.sleep(0)
        self.assertFalse(e.active)
        self.assertEqual(self.calls[-1][1],{'text':'hello'})

    async def test_trivia_progresses_through_ten_answers(self):
        e=self.engine;e.select_game('trivia');await e.start_game()
        for _ in range(10):
            await e.answer_question(0)
            e.next_question()
        await asyncio.sleep(0)
        self.assertEqual(e.quiz_correct,10)
        self.assertFalse(e.active)
        self.assertTrue(self.calls[-1][0].endswith('/finish'))

    async def test_snake_pauses_and_sends_replay(self):
        e=self.engine;e.select_game('snake');await e.start_game()
        e.pause();e.snake_tick();self.assertEqual(len(e.turns),0)
        e.pause()
        for _ in range(18):e.snake_tick()
        await asyncio.sleep(0)
        self.assertFalse(e.active)
        self.assertEqual(len(self.calls[-1][1]['turns']),18)

if __name__=='__main__':unittest.main()
