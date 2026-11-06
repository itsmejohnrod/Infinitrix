const status = document.getElementById('status');
let engine, started=false, sound=false;
window.addEventListener('error',()=>{status.textContent='Game error. Restart or check the browser console.';});
document.getElementById('play').onclick=()=>{
 if(started)return;started=true;document.getElementById('gate').hidden=true;
 engine=window.me;
 status.textContent='Loading game assets…';
 try{game.onload();
 engine.audio.setVolume(0);
 const timer=setInterval(()=>{if(window.vendorReady){clearInterval(timer);status.textContent='Ready. Click the game to focus keyboard controls.';}},200);
 setTimeout(()=>{if(!window.vendorReady){clearInterval(timer);status.textContent='Still loading. Check network access or restart the game.';}},25000);
 }catch(e){status.textContent='Could not start: '+e.message;}
};
document.getElementById('sound').onclick=()=>{
 if(!started){status.textContent='Press Play first.';return;}
 sound=!sound;engine.audio.setVolume(sound?0.35:0);document.getElementById('sound').textContent='Sound: '+(sound?'on':'off');
};
const pressed=new Set();
function releaseAll(){if(!engine)return;for(const key of pressed)engine.input.triggerKeyEvent(key,false);pressed.clear();}
document.querySelectorAll('[data-key]').forEach(button=>{
 const key=Number(button.dataset.key);
 button.onpointerdown=e=>{e.preventDefault();if(!window.vendorReady)return;button.setPointerCapture(e.pointerId);pressed.add(key);engine.input.triggerKeyEvent(key,true);};
 const up=()=>{if(engine)engine.input.triggerKeyEvent(key,false);pressed.delete(key);};
 button.onpointerup=up;button.onpointercancel=up;button.onlostpointercapture=up;
});
window.addEventListener('blur',releaseAll);
document.addEventListener('visibilitychange',()=>{releaseAll();if(document.hidden&&engine)engine.audio.setVolume(0);else if(engine)engine.audio.setVolume(sound?0.35:0);});
