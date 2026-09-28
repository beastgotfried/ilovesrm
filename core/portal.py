"""WebBridge client for the SRM eCurricula portal.

Every portal action goes through the WebBridge daemon at 127.0.0.1:10086,
which executes JS inside the logged-in Chrome tab (session 'srm-curriculum').

Safety: submit() refuses to run unless the target course code is visible in
the page — prevents cross-course contamination (arc IDs repeat across courses).
"""
import json, time, urllib.request

DAEMON = "http://127.0.0.1:10086/command"
SESSION = "srm-curriculum"

def _post(js, timeout=120):
    body = {"action": "evaluate", "args": {"code": js, "session": SESSION,
                                           "returnByValue": True, "awaitPromise": True}}
    req = urllib.request.Request(DAEMON, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        out = json.loads(r.read())
    return out.get("data", {}).get("value", out)

def up():
    try:
        v = _post("({ok:1, url:location.href})", timeout=15)
        return bool(v.get("ok"))
    except Exception:
        return False

def detect_identity():
    """Read Username (reg no) and Name from the logged-in portal page."""
    v = _post(r"""({reg:(document.body.innerText.match(/Username\s*\n?\s*(RA\d{10,})/)||[])[1]||null,
                   name:(document.body.innerText.match(/Name\s*\n?\s*([A-Z][A-Z .]+)/)||[])[1]||null,
                   loggedIn:!document.querySelector('input[type=password]')})""")
    return {"reg": v.get("reg"), "name": (v.get("name") or "").strip(),
            "logged_in": v.get("loggedIn", False)}

def open_course(course_code, tries=4):
    """Navigate to the home grid and open the course circle. Verifies identity
    by arc count > 0 AND course code present in the course view."""
    for attempt in range(tries):
        v = _post(r"""(async function(){
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
// if inside a course view, go Home first
const bc=[...document.querySelectorAll('.ant-breadcrumb a, .ant-breadcrumb span')].find(e=>(e.innerText||'').trim()==='Home');
if(bc && document.body.innerText.includes('Course Content')){
  ['mousedown','mouseup','click'].forEach(t=>bc.dispatchEvent(new MouseEvent(t,{bubbles:true,cancelable:true,view:window})));
  await sleep(6000);
}
const all=[...document.querySelectorAll('*')].filter(e=>e.children.length===0&&(e.innerText||'').trim()==='ALL'&&e.offsetParent)[0];
if(all){['mousedown','mouseup','click'].forEach(t=>all.dispatchEvent(new MouseEvent(t,{bubbles:true,cancelable:true,view:window})));await sleep(4000);}
const card=[...document.querySelectorAll('.ant-card')].find(c=>(c.innerText||'').includes('CODE'));
if(!card)return{err:'card not found'};
const img=card.querySelector('.ant-card-cover img')||card;
['mouseover','mousedown','mouseup','click'].forEach(t=>img.dispatchEvent(new MouseEvent(t,{bubbles:true,cancelable:true,view:window})));
await sleep(9000);
return {arcs:document.querySelectorAll('[id^=mainArc-]').length,
        codeVisible:document.body.innerText.includes('CODE')};
})()""".replace("CODE", course_code))
        if v.get("arcs") and v.get("codeVisible"):
            return True
        time.sleep(4)
    return False

def _guard_js(course_code):
    return f"if(!document.body.innerText.includes('{course_code}'))return {{err:'GUARD: wrong course on screen'}};"

_READ_JS = r"""
(async function(){
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
GUARD
const el=document.getElementById('ARCID');
if(!el)return {err:'no arc ARCID'};
['mousedown','mouseup','click'].forEach(t=>el.dispatchEvent(new MouseEvent(t,{bubbles:true,cancelable:true,view:window})));
await sleep(10000);
const hs=[...document.querySelectorAll('.ant-collapse-header')].filter(e=>(e.innerText||'').includes('Learning Practice'));
hs.forEach(h=>{if(!h.parentElement.className.includes('active'))h.click()});
await sleep(6000);
const items=[...document.querySelectorAll('.ant-collapse-item')].filter(p=>(p.innerText||'').includes('Learning Practice'));
const links=items.map(p=>{const a=p.querySelector('a[href*="://"]');return a?a.href:null});
const states=items.map(p=>{const h=(p.querySelector('.ant-collapse-header')||{}).innerText||'';return h.replace(/\s+/g,' ').match(/Not Completed|Pending|Completed|Verified|Empty/)?.[0]||'?'});
return {states, links};
})()
"""

_SUBMIT_JS = r"""
(async function(){
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
GUARD
const el=document.getElementById('ARCID');
if(!el)return {err:'no arc ARCID'};
['mousedown','mouseup','click'].forEach(t=>el.dispatchEvent(new MouseEvent(t,{bubbles:true,cancelable:true,view:window})));
await sleep(9000);
const hs=[...document.querySelectorAll('.ant-collapse-header')].filter(e=>(e.innerText||'').includes('Learning Practice'));
hs.forEach(h=>{if(!h.parentElement.className.includes('active'))h.click()});
await sleep(5000);
const inputs=[...document.querySelectorAll('input')].filter(i=>(i.placeholder||'').toLowerCase().includes('worksheet answer pdf'));
const links=LINKS;
const setter=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;
const log=[];
for(let idx=0;idx<inputs.length&&idx<links.length;idx++){
  const inp=inputs[idx];
  setter.call(inp,links[idx]);
  inp.dispatchEvent(new Event('input',{bubbles:true}));
  await sleep(400);
  const scope=inp.closest('.ant-collapse-content')||inp.closest('div')||document;
  const btn=[...scope.querySelectorAll('button')].find(b=>/update/i.test(b.innerText||''));
  if(btn){btn.click();log.push(idx+':clicked')}else{log.push(idx+':nobtn')}
  await sleep(2500);
  const msg=document.querySelector('.ant-message');
  log.push(idx+':'+(msg?msg.innerText.replace(/\s+/g,' ').slice(0,50):'nomsg'));
}
return {log, nIn:inputs.length, ok:log.some(m=>/ubmitted successfully/.test(m))};
})()
"""

def arc_id(unit, session, slo=1):
    return f"mainArc-{unit}0{session}{slo}" if session < 10 else f"mainArc-{unit}{session}{slo}"

def read_slot(course_code, unit, session, retries=3):
    """Return {'states':[...], 'links':[url|None,...]} for one session (both SLOs)."""
    js = _READ_JS.replace("ARCID", arc_id(unit, session)).replace("GUARD", _guard_js(course_code))
    for attempt in range(retries):
        v = _post(js)
        if v.get("err"):
            if "GUARD" in v["err"]:
                raise RuntimeError(v["err"])
        elif v.get("states"):
            return v
        time.sleep(6 + attempt * 4)
    return {"states": [], "links": []}

def submit_links(course_code, unit, session, urls, retries=4):
    """Submit [slot1_url, slot2_url] into one session. Returns True on success."""
    js = (_SUBMIT_JS.replace("ARCID", arc_id(unit, session))
                    .replace("GUARD", _guard_js(course_code))
                    .replace("LINKS", json.dumps(urls)))
    for attempt in range(retries):
        v = _post(js)
        if v.get("err"):
            if "GUARD" in v["err"]:
                raise RuntimeError(v["err"])
        elif v.get("nIn") == len(urls) and v.get("ok"):
            return True
        time.sleep(6 + attempt * 4)
    return False
