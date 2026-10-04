"""Record the data flow between the Rivoli twin components and write a self-contained HTML replay.

Does NOT modify the project: it wraps a few methods at run time (monkey patching) and then runs the normal `run()`.
Usage (from the project folder, with the venv active):
    python trace_flow.py                              # twin, medium penalty
    python trace_flow.py --fail A2@15:30-16:10        # sensor A2 offline
    python trace_flow.py --res high --out flow_high.html
Open the HTML file in a browser. Standard library only.
"""
import argparse, json
from rivoli_twin.config import parse_hhmm, fmt
from rivoli_twin.scenario_generator import Scenario, Surge, SensorFailure, build_baseline_profiles
from rivoli_twin.system import run, RunConfig
from rivoli_twin.broker import InMemoryBroker
from rivoli_twin.sensors import SensorSimulator
from rivoli_twin.traffic_management import TrafficManagementService
from rivoli_twin.simulation_bridge import LocalSimulationBridge

recs, cur = [], {}
DEMO = r'''<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><title>Rivoli Twin: message sequence + VMS</title>
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<style>
:root{--bg:#f4faf9;--card:#fff;--tx:#1f2937;--mu:#6b7280;--ac:#0f766e;--co:#e11d48;--bd:#d9e2e1;box-sizing:border-box;padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px)}
@media(prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#0b1f33;--card:#12304a;--tx:#e8eef5;--mu:#9fb3c8;--ac:#2dd4bf;--co:#fb7185;--bd:#264a68}}
:root[data-theme="dark"]{--bg:#0b1f33;--card:#12304a;--tx:#e8eef5;--mu:#9fb3c8;--ac:#2dd4bf;--co:#fb7185;--bd:#264a68}
html{scroll-padding-top:env(safe-area-inset-top,0px)}body{margin:0;background:var(--bg);color:var(--tx);font-family:Calibri,"Segoe UI",system-ui,sans-serif;padding:14px}
.w{max-width:1100px;margin:0 auto}h1{font-size:22px;margin:0}.s{color:var(--mu);font-size:13px;margin:2px 0 10px}
.card{background:var(--card);border:1px solid var(--bd);border-radius:10px;padding:10px;margin-bottom:10px}
.ctl{display:flex;gap:8px;align-items:center;flex-wrap:wrap}.ctl input{flex:1;min-width:120px}
button,select{font:inherit;padding:6px 12px;border-radius:8px;border:1px solid var(--bd);background:var(--card);color:var(--tx)}button.p{background:var(--ac);color:#fff;border:0;font-weight:700}
svg{width:100%;height:auto;display:block}text{font-family:inherit;fill:var(--tx)}
.g{display:grid;grid-template-columns:1.25fr 1fr;gap:10px}.g2{display:grid;grid-template-columns:1fr 1fr;gap:10px}@media(max-width:760px){.g,.g2{grid-template-columns:1fr}}
h3{font-size:13px;margin:0 0 6px;color:var(--mu);text-transform:uppercase;letter-spacing:.04em}
.vms{background:#111;border:4px solid #222;border-radius:8px;padding:12px;font:700 14px/1.6 "Courier New",monospace;overflow-x:auto;white-space:pre}
.act{margin-top:8px;padding:8px;border-radius:8px;font-size:13px}.l{font:11.5px/1.5 ui-monospace,Menlo,Consolas,monospace;max-height:200px;overflow:auto}.l div{white-space:nowrap}
.tg{display:inline-block;min-width:54px;padding:0 6px;border-radius:5px;color:#fff;font-size:10.5px;font-weight:700;margin-right:6px;text-align:center}
.sg{transition:opacity .25s}
</style></head><body><div class="w">
<h1>Message sequence and VMS behaviour, side by side</h1><p class="s" id="ttl"></p>
<div class="card ctl"><button class="p" id="pl">Play</button><button id="nx">Next decision</button><input id="sl" type="range" min="0" value="0"><b id="clk" style="min-width:48px">14:01</b>
<select id="sp"><option value="5">Slow</option><option value="2.5" selected>Normal</option><option value="1">Fast</option></select></div>
<div class="g"><div class="card"><h3>Message sequence, one control minute</h3><svg id="sq" viewBox="0 0 570 385"></svg></div>
<div><div class="card"><h3>VMS at Concorde (what drivers see)</h3><div class="vms" id="vms"></div><div class="act" id="act"></div><div class="l" id="cs" style="margin-top:6px"></div></div>
<div class="card"><h3>Road as the twin sees it (load index λ)</h3><svg id="mp" viewBox="0 0 400 190"></svg><div class="s" style="margin:0">Green &lt; 0.6, amber &lt; 0.8, red ≥ 0.8. Amber halo = inferred (sensor offline).</div></div></div></div>
<div class="g2"><div class="card"><h3>Messages through the broker this minute</h3><div class="l" id="ms"></div></div>
<div class="card"><h3>Decisions logged this minute</h3><div class="l" id="lg"></div></div></div>
</div><script>
const D=__DATA__,R=D.recs,N=R.length,NS='http://www.w3.org/2000/svg',$=i=>document.getElementById(i);$('ttl').textContent=D.title;
const E=(p,t,a,x)=>{const e=document.createElementNS(NS,t);for(const k in a)e.setAttribute(k,a[k]);if(x!=null)e.textContent=x;p.appendChild(e);return e};
const sq=$('sq'),PX=[50,145,240,335,430,525],PN=['Simulator','Bridge','Sensors','Broker','Twin core','Traffic mgmt'];
PX.forEach((x,k)=>{E(sq,'rect',{x:x-44,y:6,width:88,height:28,rx:6,fill:'var(--card)',stroke:'var(--ac)','stroke-width':2});E(sq,'text',{x,y:25,'text-anchor':'middle','font-size':12,'font-weight':700},PN[k]);E(sq,'line',{x1:x,y1:34,x2:x,y2:378,stroke:'var(--bd)','stroke-width':2,'stroke-dasharray':'4 4'})});
const A=[[0,1],[1,2],[2,3],[3,4],[4,3],[3,5],[5,1],[1,0]],TH=[.05,.15,.28,.42,.55,.68,.82,.93],G=[];
A.forEach(([a,b],k)=>{const y=72+k*38,g=E(sq,'g',{class:'sg'}),s=b>a?1:-1;g.line=E(g,'line',{x1:PX[a],y1:y,x2:PX[b]-s*2,y2:y,'stroke-width':2.5});g.tri=E(g,'polygon',{points:`${PX[b]},${y} ${PX[b]-8*s},${y-4.5} ${PX[b]-8*s},${y+4.5}`});
 g.t=E(g,'text',{x:(PX[a]+PX[b])/2,y:y-6,'text-anchor':'middle','font-size':11.5});G.push(g)});
const mp=$('mp');const SG={C1:[95,35,195,35],C2:[200,35,300,35],A1:[60,95,140,95],A2:[145,95,245,95],A3:[250,95,330,95],B1:[95,155,195,155],B2:[200,155,300,155]},ML={};
[['M40 95 L95 35','M300 35 L350 95'],['M40 95 L330 95','M330 95 L350 95'],['M40 95 L95 155','M300 155 L350 95']].forEach(p=>p.forEach(d=>E(mp,'path',{d,stroke:'var(--bd)','stroke-width':7,fill:'none','stroke-linecap':'round'})));
for(const k in SG){const[a,b,c,d]=SG[k];const h=E(mp,'line',{x1:a,y1:b,x2:c,y2:d,stroke:'#fbbf24','stroke-width':15,'stroke-linecap':'round',opacity:0});const l=E(mp,'line',{x1:a,y1:b,x2:c,y2:d,stroke:'#9ca3af','stroke-width':9,'stroke-linecap':'round'});E(mp,'text',{x:(a+c)/2,y:b+(b<95?-9:b>95?20:20),'text-anchor':'middle','font-size':12,'font-weight':700},k);ML[k]=[l,h]}
E(mp,'circle',{cx:48,cy:95,r:9,fill:'#2563eb',stroke:'#fff','stroke-width':2});E(mp,'text',{x:48,y:122,'text-anchor':'middle','font-size':11,'font-weight':700,style:'fill:#2563eb'},'VMS');
E(mp,'text',{x:200,y:14,'text-anchor':'middle','font-size':12,'font-weight':700,style:'fill:var(--mu)'},'C  Saint-Honoré (residential)');E(mp,'text',{x:200,y:70,'text-anchor':'middle','font-size':12,'font-weight':700,style:'fill:var(--mu)'},'A  Rivoli');E(mp,'text',{x:200,y:186,'text-anchor':'middle','font-size':12,'font-weight':700,style:'fill:var(--mu)'},'B  Quais');
const COL=v=>v<.6?'#28a745':v<.8?'#e0a800':'#dc3545',TAG={SENSOR:'#d97706',TWIN:'#2563eb',REQ1:'#0f766e',REQ2:'#e11d48',ROUTE:'#6b7280',MONITOR:'#6b7280'};
let i=0,u=0,pl=false,last=0;const sl=$('sl');sl.max=N-1;
function seqShow(){const uu=pl?u:1;let top=-1;TH.forEach((t,k)=>{if(uu>=t)top=k});G.forEach((g,k)=>{const on=k<=top,act=k>=6?(R[i].cmds.length||R[i].split>0):true,c=k>=6?(act?'var(--co)':'var(--bd)'):(k==4||k==5?'#d97706':'var(--ac)');
 g.style.opacity=on?(act?1:.5):0;g.line.setAttribute('stroke',c);g.tri.setAttribute('fill',c);g.line.setAttribute('stroke-width',k==top&&pl?4:2.5);g.t.style.fill=c})}
function panels(){const r=R[i];sl.value=i;$('clk').textContent=r.t;const n=r.msgs.filter(x=>x[0]!='t').length,mx=Object.entries(r.seg).sort((a,b)=>b[1][0]-a[1][0])[0],act=r.cmds.length||r.split>0;
 const lb=['read all segments','5 s samples, 12 per minute','publish '+n+' msgs (speed, detector, tick)','deliver '+n+' msgs','twin/state, max load '+mx[1][0].toFixed(2)+' on '+mx[0],'twin/state',r.cmds.length?'set_green '+r.cmds.map(c=>c[0]+' '+c[1]+'s').join(', '):(r.split>0?'route split '+Math.round(r.split*100)+' %':'no action'),act?'apply to road':''];
 G.forEach((g,k)=>g.t.textContent=lb[k]);
 const tt=r.tt||{A:0,B:0,C:0},p=r.p||{B:.5,C:.5},rec=r.split>0?(p.B>=p.C?'B':'C'):'A',cl=k=>k==rec?'#ff8c00':'#663300',f=k=>String(Math.round(tt[k])).padStart(2);
 $('vms').innerHTML=`<span style="color:${cl('A')}">Rivoli (A)    : Temps estimé : ${f('A')} min</span>\n<span style="color:${cl('C')}">St-Honoré (C) : Temps estimé : ${f('C')} min</span>\n<span style="color:${cl('B')}">Quais (B)     : Temps estimé : ${f('B')} min</span>`;
 const a=$('act');if(r.split>0){a.style.background='rgba(37,99,235,.15)';a.innerHTML=`<b>Current action:</b> main corridor congested, VMS diverts <b>${Math.round(r.split*100)} %</b>: ${Math.round((1-r.split)*100)} % stay on A, ${Math.round(r.split*p.C*100)} % go to C (residential), ${Math.round(r.split*p.B*100)} % go to B (quais).`}
 else{a.style.background='rgba(40,167,69,.15)';a.innerHTML='<b>Current action:</b> traffic is fluid on the main corridor. VMS recommends staying on Route A (100 %).'}
 $('cs').innerHTML=r.costs?`<div>Routing costs (min): A ${r.costs.A} · B ${r.costs.B} · C ${r.costs.C}</div>`:'';
 for(const k in ML){const s=r.seg[k];ML[k][0].setAttribute('stroke',s?COL(s[0]):'#9ca3af');ML[k][1].setAttribute('opacity',s&&s[1]=='i'?.9:0)}
 $('ms').innerHTML=r.msgs.map(x=>`<div><span class="tg" style="background:${{s:'#0f766e',d:'#2563eb',c:'#6b7280',t:'#d97706'}[x[0]]}">${{t:'state',s:'speed',d:'detector',c:'tick'}[x[0]]}</span>${x[1]}</div>`).join('');
 const lg=r.logs.filter(x=>x[0]!='ROUTE').map(x=>`<div style="white-space:normal"><span class="tg" style="background:${TAG[x[0]]||'#6b7280'}">${x[0]}</span>${x[1]}</div>`);if(r.costs)lg.push(`<div style="white-space:normal"><span class="tg" style="background:#6b7280">ROUTE</span>cost A ${r.costs.A} / B ${r.costs.B} / C ${r.costs.C} min · divert ${Math.round(r.split*100)} %</div>`);
 $('lg').innerHTML=lg.join('');seqShow()}
function tick(t){if(!pl)return;u+=(t-last)/1000/$('sp').value;last=t;if(u>=1){u=0;if(i<N-1){i++;panels()}else{pl=false;$('pl').textContent='Replay';seqShow();return}}seqShow();requestAnimationFrame(tick)}
$('pl').onclick=()=>{if(pl){pl=false;$('pl').textContent='Play';seqShow();return}if(i>=N-1){i=0;panels()}pl=true;u=0;$('pl').textContent='Pause';last=performance.now();requestAnimationFrame(tick)};
sl.oninput=()=>{i=+sl.value;u=0;pl=false;$('pl').textContent='Play';panels()};
$('nx').onclick=()=>{for(let k=i+1;k<N;k++)if(R[k].logs.some(x=>x[0]!='ROUTE')){i=k;u=0;panels();return}};
panels();
</script></body></html>
'''
TEMPLATE = r'''<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><title>Rivoli Twin: data flow</title>
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<style>
:root{--bg:#f4faf9;--card:#fff;--tx:#1f2937;--mu:#6b7280;--ac:#0f766e;--bl:#2563eb;--am:#d97706;--co:#e11d48;--bd:#d9e2e1;box-sizing:border-box;padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px)}
@media(prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#0b1f33;--card:#12304a;--tx:#e8eef5;--mu:#9fb3c8;--ac:#2dd4bf;--bl:#60a5fa;--am:#fbbf24;--co:#fb7185;--bd:#264a68}}
:root[data-theme="dark"]{--bg:#0b1f33;--card:#12304a;--tx:#e8eef5;--mu:#9fb3c8;--ac:#2dd4bf;--bl:#60a5fa;--am:#fbbf24;--co:#fb7185;--bd:#264a68}
html{scroll-padding-top:env(safe-area-inset-top,0px)}body{margin:0;background:var(--bg);color:var(--tx);font-family:Calibri,"Segoe UI",system-ui,sans-serif;padding:14px}
.w{max-width:900px;margin:0 auto}h1{font-size:22px;margin:0}.s{color:var(--mu);font-size:13px;margin:2px 0 10px}
.card{background:var(--card);border:1px solid var(--bd);border-radius:10px;padding:10px;margin-bottom:10px}
.ctl{display:flex;gap:8px;align-items:center;flex-wrap:wrap}.ctl input{flex:1;min-width:120px}
button,select{font:inherit;padding:6px 12px;border-radius:8px;border:1px solid var(--bd);background:var(--card);color:var(--tx)}button.p{background:var(--ac);color:#fff;border:0;font-weight:700}
svg{width:100%;height:auto;display:block}text{font-family:inherit;fill:var(--tx)}
.g{display:grid;grid-template-columns:1fr 1fr;gap:10px}@media(max-width:640px){.g{grid-template-columns:1fr}}
h3{font-size:13px;margin:0 0 6px;color:var(--mu);text-transform:uppercase;letter-spacing:.04em}
.l{font:11.5px/1.5 ui-monospace,Menlo,Consolas,monospace;max-height:210px;overflow:auto}.l div{white-space:nowrap}
.tg{display:inline-block;min-width:54px;padding:0 6px;border-radius:5px;color:#fff;font-size:10.5px;font-weight:700;margin-right:6px;text-align:center}
.chips{display:flex;gap:6px;flex-wrap:wrap}.chip{padding:3px 8px;border-radius:6px;color:#fff;font-size:12px;font-weight:700;border:2px solid transparent}
.lg{font-size:12px;color:var(--mu)}.lg b{display:inline-block;width:10px;height:10px;border-radius:50%;margin:0 4px 0 10px}
</style></head><body><div class="w">
<h1>Rivoli Digital Twin: how the data flows</h1><p class="s" id="ttl"></p>
<div class="card ctl"><button class="p" id="pl">Play</button><button id="nx">Next decision</button><input id="sl" type="range" min="0" value="0"><b id="clk" style="min-width:48px">14:01</b>
<select id="sp"><option value="4">Slow</option><option value="2" selected>Normal</option><option value="0.8">Fast</option></select></div>
<div class="card"><svg id="d" viewBox="0 0 720 330"></svg>
<div class="lg"><b style="background:var(--ac)"></b>speed<b style="background:var(--bl)"></b>detector<b style="background:var(--mu)"></b>cycle tick<b style="background:var(--am)"></b>twin/state<b style="background:var(--co)"></b>action (green time, route split)</div></div>
<div class="card"><h3>State of each segment (load index λ, as the twin sees it)</h3><div class="chips" id="ch"></div><div class="lg">Dashed amber outline = inferred (sensor offline)</div></div>
<div class="g"><div class="card"><h3>Messages through the broker this minute</h3><div class="l" id="ms"></div></div>
<div class="card"><h3>Decisions logged this minute</h3><div class="l" id="lg"></div></div></div>
</div><script>
const D=__DATA__,R=D.recs,N=R.length,NS='http://www.w3.org/2000/svg',$=i=>document.getElementById(i);
$('ttl').textContent=D.title;
const E=(p,t,a,x)=>{const e=document.createElementNS(NS,t);for(const k in a)e.setAttribute(k,a[k]);if(x!=null)e.textContent=x;p.appendChild(e);return e};
const svg=$('d'),B={};
const box=(id,x,y,n,sub)=>{const r=E(svg,'rect',{x,y,width:190,height:52,rx:8,fill:'var(--card)',stroke:'var(--ac)','stroke-width':2});E(svg,'text',{x:x+95,y:y+21,'text-anchor':'middle','font-size':14,'font-weight':700},n);B[id]={r,s:E(svg,'text',{x:x+95,y:y+39,'text-anchor':'middle','font-size':11,style:'fill:var(--mu)'},sub)}};
const L=(x1,y1,x2,y2,c)=>E(svg,'line',{x1,y1,x2,y2,stroke:c||'var(--bd)','stroke-width':2});
L(205,58,265,58);L(455,58,515,58);L(265,34,205,34);L(300,250,300,72,'var(--co)');L(360,175,360,250);L(570,175,570,250);L(680,250,680,175);L(610,72,610,135);
B.bus={r:E(svg,'rect',{x:15,y:135,width:690,height:40,rx:8,fill:'var(--ac)'})};
E(svg,'text',{x:30,y:160,'font-size':14,'font-weight':700,style:'fill:#fff'},'Message broker');
E(svg,'text',{x:190,y:160,'font-size':10.5,style:'fill:#fff'},'paris/rivoli/{seg}/speed · /detector · /cycle · twin/state');
box('sim',15,20,'Traffic simulator','');box('br',265,20,'Simulation bridge','');box('se',515,20,'Sensor simulator','');
box('tm',265,250,'Traffic management','');box('tw',515,250,'Digital Twin core','');
E(svg,'text',{x:15,y:322,'font-size':11,style:'fill:var(--mu)'},'Orange path = actions from traffic management back to the road (green time, route split)');
const P=E(svg,'g',{});
const X=i=>540+i*13.5,CS={s:'var(--ac)',d:'var(--bl)',c:'var(--mu)',t:'var(--am)'};
const WIN={sim:[0,.1,.92,1],br:[0,.2,.78,1],se:[.1,.4],bus:[.2,.78],tw:[.4,.7],tm:[.65,.95]};
let i=0,u=0,pl=false,last=0;const sl=$('sl');sl.max=N-1;
const lerp=(a,b,f)=>a+(b-a)*f,seg=(a,u0,u1)=>Math.max(0,Math.min(1,(u-u0)/(u1-u0)));
function dot(x,y,c,r){E(P,'circle',{cx:x,cy:y,r:r||4.5,fill:c})}
function particles(){P.replaceChildren();const r=R[i];if(u<=0||u>=1)return;
 const act=r.cmds.length||r.vms||r.split>0;
 let f=seg(0,.1);if(f>0&&f<1){dot(lerp(205,265,f),58,CS.c)}
 f=seg(0,.1,.2);if(f>0&&f<1)dot(lerp(455,515,f),58,CS.c);
 const m=r.msgs.filter(x=>x[0]!='t');
 m.forEach((x,k)=>{const s0=.2+k*.012;let f=seg(0,s0,s0+.08);if(f>0&&f<1)dot(X(k),lerp(72,135,f),CS[x[0]]);
  f=seg(0,.4,.52);if(f>0&&f<1&&u>.4)dot(X(k)-20,lerp(175,250,f),CS[x[0]],3.5)});
 f=seg(0,.55,.65);if(f>0&&f<1)dot(680,lerp(250,175,f),CS.t,6);
 f=seg(0,.65,.75);if(f>0&&f<1)dot(360,lerp(175,250,f),CS.t,6);
 f=seg(0,.78,.92);if(f>0&&f<1){const c=act?'var(--co)':'var(--bd)';dot(300,lerp(250,72,f),c,6);if(f>.9)dot(lerp(265,205,seg(0,.92,1)),34,c,5)}
 f=seg(0,.92,1);if(f>0&&f<1)dot(lerp(265,205,f),34,act?'var(--co)':'var(--bd)',5);
 for(const k in WIN){const w=WIN[k],on=(u>=w[0]&&u<=w[1])||(w[2]!==undefined&&u>=w[2]&&u<=w[3]);B[k].r.setAttribute('stroke-width',on?5:2);if(k=='bus')B[k].r.setAttribute('opacity',on?1:.75)}}
const COL=v=>v<.6?'#28a745':v<.8?'#d39e00':'#dc3545',TAG={SENSOR:'#d97706',TWIN:'#2563eb',REQ1:'#0f766e',REQ2:'#e11d48',ROUTE:'#6b7280',MONITOR:'#6b7280'};
function panels(){const r=R[i];sl.value=i;$('clk').textContent=r.t;
 B.sim.s.textContent='minute '+r.t;B.se.s.textContent=r.msgs.length-1+' msgs / min';B.br.s.textContent=r.cmds.length?'set green '+r.cmds.map(c=>c[0]+' '+c[1]+'s').join(', '):'reads + applies';
 const mx=Object.entries(r.seg).sort((a,b)=>b[1][0]-a[1][0])[0];B.tw.s.textContent=mx?'max load '+mx[1][0].toFixed(2)+' on '+mx[0]:'';
 B.tm.s.textContent=(r.vms?'VMS ON':'VMS off')+(r.vms?' · divert '+Math.round(r.split*100)+' %':'');
 $('ch').replaceChildren();for(const k in r.seg){const[v,s]=r.seg[k],c=document.createElement('span');c.className='chip';c.style.background=COL(v);c.style.borderColor=s=='i'?'#fbbf24':'transparent';if(s=='i')c.style.borderStyle='dashed';c.textContent=k+'  '+v.toFixed(2);$('ch').appendChild(c)}
 $('ms').innerHTML=r.msgs.map(x=>`<div><span class="tg" style="background:${{s:'#0f766e',d:'#2563eb',c:'#6b7280',t:'#d97706'}[x[0]]}">${x[0]=='t'?'state':x[0]=='s'?'speed':x[0]=='d'?'detector':'tick'}</span>${x[1]}</div>`).join('');
 const lg=r.logs.filter(x=>x[0]!='ROUTE').map(x=>`<div style="white-space:normal"><span class="tg" style="background:${TAG[x[0]]||'#6b7280'}">${x[0]}</span>${x[1]}</div>`);
 if(r.costs)lg.push(`<div style="white-space:normal"><span class="tg" style="background:#6b7280">ROUTE</span>cost A ${r.costs.A} / B ${r.costs.B} / C ${r.costs.C} min · p(B) ${r.p.B} · divert ${Math.round(r.split*100)} %</div>`);
 $('lg').innerHTML=lg.join('');particles()}
function tick(t){if(!pl)return;u+=(t-last)/1000/$('sp').value;last=t;if(u>=1){u=0;if(i<N-1){i++;panels()}else{pl=false;$('pl').textContent='Replay';return}}particles();requestAnimationFrame(tick)}
$('pl').onclick=()=>{if(pl){pl=false;$('pl').textContent='Play';return}if(i>=N-1){i=0;panels()}pl=true;u=0;$('pl').textContent='Pause';last=performance.now();requestAnimationFrame(tick)};
sl.oninput=()=>{i=+sl.value;u=0;panels()};
$('nx').onclick=()=>{for(let k=i+1;k<N;k++)if(R[k].logs.some(x=>x[0]!='ROUTE')){i=k;u=0;panels();return}};
panels();
</script></body></html>
'''


def install():
    o_pub = SensorSimulator._publish
    def sensors_publish(self, t):                       # start of one minute: sensors publish
        global cur
        cur = {"t": fmt(t), "k": t, "msgs": [], "cmds": [], "logs": [], "seg": {}}
        recs.append(cur)
        return o_pub(self, t)
    SensorSimulator._publish = sensors_publish

    o_bp = InMemoryBroker.publish
    def broker_publish(self, topic, payload):           # every message through the broker
        if cur:
            p = topic.split("/")
            if topic == "twin/state":
                segs = payload["segments"]
                cur["seg"] = {k: [round(v["vc"], 2), "i" if v["source"] != "observed" else "o", round(v["speed_kmh"])] for k, v in segs.items()}
                mx = max(segs, key=lambda k: segs[k]["vc"])
                cur["msgs"].append(["t", f"twin/state  {len(segs)} segments, max load {segs[mx]['vc']:.2f} on {mx}"])
            elif p[-1] == "speed":
                v = payload.get("v_avg")
                cur["msgs"].append(["s", f"{p[2]}/speed  " + (f"{v} km/h" if v is not None else "OFFLINE")])
            elif p[-1] == "detector":
                cur["msgs"].append(["d", f"{p[2]}/detector  queue {payload['queue_max']:.2f}, red {payload['red_share']:.2f}"])
            else:
                cur["msgs"].append(["c", "cycle  tick"])
        return o_bp(self, topic, payload)
    InMemoryBroker.publish = broker_publish

    o_tms = TrafficManagementService.on_state
    def tms_on_state(self, topic, msg):                 # traffic management reacts to twin/state
        r = o_tms(self, topic, msg)
        cur["vms"], cur["split"] = int(self.vms.on), round(self.distribution.divert_share, 2)
        for (_, tag, _, meta) in reversed(self.log.entries):
            if tag == "ROUTE" and meta:
                m = json.loads(meta); cur["costs"], cur["p"], cur["prev"], cur["tt"] = m["costs"], m["probabilities"], m["previous_minute_stats"], m["travel_min"]; break
        return r
    TrafficManagementService.on_state = tms_on_state

    o_sg = LocalSimulationBridge.set_green
    def set_green(self, segment_id, green_s):           # command sent to the simulator
        if cur: cur["cmds"].append([segment_id, green_s])
        return o_sg(self, segment_id, green_s)
    LocalSimulationBridge.set_green = set_green

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--res", default="medium", choices=["low", "medium", "high"])
    ap.add_argument("--fail", action="append", default=[], help="SEG@HH:MM-HH:MM")
    ap.add_argument("--surge", action="append", default=[], help="HH:MM")
    ap.add_argument("--out", default="flow_replay.html", help="component flow animation")
    ap.add_argument("--demo", default="demo.html", help="message sequence + VMS side by side")
    a = ap.parse_args()
    sc = Scenario(seed=7)
    for f in a.fail:
        seg, win = f.split("@"); s, e = win.split("-")
        sc.sensor_failures.append(SensorFailure(seg, parse_hhmm(s), parse_hhmm(e)))
    for s in a.surge:
        st = parse_hhmm(s); sc.surges.append(Surge(st, st + 1200))
    profiles = build_baseline_profiles(seed=99)
    install()
    _, log = run(sc, RunConfig(f"traced {a.res}", True, a.res), profiles)
    by_t = {r["k"]: r for r in recs}
    for (t, tag, text, _) in log.entries:
        if t in by_t: by_t[t]["logs"].append([tag, text[:230]])
    title = f"Twin, {a.res} residential penalty" + ("".join(f", sensor {f.split('@')[0]} offline {f.split('@')[1]}" for f in a.fail)) + ("".join(f", surge {s}" for s in a.surge))
    html = TEMPLATE.replace("__DATA__", json.dumps({"title": title, "recs": recs}, separators=(",", ":")))
    open(a.out, "w", encoding="utf-8").write(html)
    data = json.dumps({"title": title, "recs": recs}, separators=(",", ":"))
    open(a.demo, "w", encoding="utf-8").write(DEMO.replace("__DATA__", data))
    print(f"{len(recs)} minutes traced -> {a.out}, {a.demo}")

if __name__ == "__main__":
    main()
