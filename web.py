"""Small local dashboard and scheduler for the chicken counter."""
import datetime as dt
import fcntl
import html
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import os
from pathlib import Path
import secrets
import threading
import time
from urllib.parse import urlsplit, unquote
from zoneinfo import ZoneInfo
import counter

DATA = Path(os.environ.get("DATA_DIR", "/data"))
ZONE = ZoneInfo(os.environ.get("TZ", "America/New_York"))
TOKEN = secrets.token_urlsafe(32)
MUTEX = threading.Lock()
STATE_LOCK = threading.Lock()
STATE = {"running": False, "error": None}
LOG = logging.getLogger("dashboard")


def history():
    db = counter.connect(DATA)
    try:
        rows = db.execute("SELECT id,created,status,result FROM runs ORDER BY id DESC LIMIT 20").fetchall()
        return [{"id":r[0], "created":r[1], "status":r[2], "result":json.loads(r[3])} for r in rows]
    finally:
        db.close()


def perform(coop_id=None, scheduled=False):
    with (DATA / "counter.lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("Another chicken check is running")
        db = counter.connect(DATA)
        try:
            # Persist the image folder in results without changing the counting code.
            before = set(DATA.glob("run-*"))
            result = counter.run(DATA, db, ZONE, scheduled=scheduled, coop_id=coop_id)
            created = set(DATA.glob("run-*")) - before
            if len(created) == 1:
                result["image_folder"] = created.pop().name
                row_id = db.execute("SELECT max(id) FROM runs").fetchone()[0]
                db.execute("UPDATE runs SET result=? WHERE id=?", (json.dumps(result),row_id))
                db.commit()
                (DATA / result["image_folder"] / "result.json").write_text(json.dumps(result,indent=2))
            return result
        finally:
            db.close()


def worker(coop_id, scheduled):
    try:
        perform(coop_id, scheduled)
    except Exception as exc:
        LOG.error("Dashboard check failed (%s)",type(exc).__name__)
        with STATE_LOCK:
            STATE["error"] = str(exc) if isinstance(exc,RuntimeError) else "Check failed; see container logs"
    finally:
        with STATE_LOCK:
            STATE["running"] = False
        MUTEX.release()


def start(coop_id=None, scheduled=False):
    if not MUTEX.acquire(blocking=False):
        return False
    with STATE_LOCK:
        STATE.update(running=True,error=None)
    threading.Thread(target=worker,args=(coop_id,scheduled),daemon=True).start()
    return True


def scheduler():
    hour, minute = map(int,os.environ.get("CHECK_TIME","22:00").split(":"))
    dt.time(hour,minute)
    LOG.info("Nightly check at %02d:%02d %s",hour,minute,ZONE)
    while True:
        try:
            now = dt.datetime.now(ZONE)
            db = counter.connect(DATA)
            try:
                done = db.execute("SELECT 1 FROM runs WHERE local_date=? AND scheduled=1",
                                  (now.date().isoformat(),)).fetchone()
            finally:
                db.close()
            if (now.hour,now.minute) >= (hour,minute) and not done:
                start(scheduled=True)
        except Exception:
            LOG.exception("Scheduler error")
        time.sleep(20)


PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Chicken checks</title><style>
:root{font-family:system-ui,sans-serif;color:#24362e;background:#f4f6f2}body{max-width:1050px;margin:40px auto;padding:0 20px}
h1{margin-bottom:6px}p{line-height:1.5}.sub{color:#647368}button{background:#245e43;color:white;border:0;border-radius:9px;padding:12px 18px;cursor:pointer;font-size:15px;margin:5px 8px 5px 0}
button:disabled{opacity:.5;cursor:wait}.card{background:white;border:1px solid #dce3d9;border-radius:14px;padding:20px;margin:16px 0}.ok{color:#247044}.warn{color:#ad5c10}.bad{color:#ba3333}.photos{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:10px}img{width:100%;border-radius:8px}small,.meta{color:#647368}.row{display:flex;justify-content:space-between;gap:15px;align-items:center}select{padding:9px;max-width:100%}pre{white-space:pre-wrap}#error{color:#ba3333}
</style></head><body><h1>Chicken checks</h1><p class="sub" id="schedule"></p>
<div id="buttons"></div><button id="hue-off" onclick="lightOff()">Turn light off</button><span id="light-status" role="status"></span><p id="running" role="status"></p><p id="error"></p>
<div class="row"><h2 id="heading">Latest results</h2><select id="history" aria-label="Select recent check"></select></div>
<div id="results"></div><script>
let token="",selected=null,busy=false,configured=false;
const esc=s=>String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const label=s=>({observed_expected:"All accounted for",check_needed:"Please check",error:"Check failed"}[s]||s);
async function lightOff(){
const button=document.getElementById("hue-off");button.disabled=true;
const status=document.getElementById("light-status");status.textContent=" Turning light off…";
try{const response=await fetch("/api/hue/off",{method:"POST",headers:{"X-Check-Token":token}});
const data=await response.json();if(!response.ok)throw Error(data.error);
status.textContent=" Light turned off.";
}catch(e){status.textContent=" "+e.message}
finally{button.disabled=busy}}
async function check(coop){document.querySelectorAll("button").forEach(b=>b.disabled=true);
try{const r=await fetch("/api/check",{method:"POST",headers:{"Content-Type":"application/json","X-Check-Token":token},body:JSON.stringify({coop})});
const data=await r.json();if(!r.ok)throw Error(data.error);selected=null;await refresh();
}catch(e){document.getElementById("error").textContent=e.message} }
function render(run){const box=document.getElementById("results");if(!run){box.innerHTML='<div class="card">No checks yet. Run a check above.</div>';return}
const r=run.result;box.innerHTML='<p class="meta">'+esc(run.created)+' · '+esc(label(run.status))+'</p>'+
r.coops.map(c=>{let cls=c.status==="observed_expected"?"ok":c.status==="error"?"bad":"warn";
let pics=r.image_folder?c.frames.map((f,i)=>'<div><a target="_blank" href="/images/'+encodeURIComponent(r.image_folder)+'/coop-'+c.id+'/frame-'+String(i+1).padStart(2,"0")+'.jpg"><img loading="lazy" alt="'+esc(c.name)+' frame '+(i+1)+'" src="/images/'+encodeURIComponent(r.image_folder)+'/coop-'+c.id+'/frame-'+String(i+1).padStart(2,"0")+'.jpg"></a><p><strong>'+f.count+' visible</strong> · '+(f.clear?'Clear':'Unclear')+'</p><small>'+esc(f.locations.join("; "))+'</small><p>'+esc(f.note)+'</p></div>').join(""):"";
return '<section class="card"><h2>'+esc(c.name)+'</h2><p class="'+cls+'"><strong>'+esc(label(c.status))+'</strong> · Expected '+c.expected+' · Counts ['+c.frames.map(f=>f.count).join(",")+']</p>'+
(c.error?'<p class="bad">'+esc(c.error)+'</p>':'')+'<div class="photos">'+pics+'</div></section>'}).join("")+
'<p class="meta">ntfy: '+esc(r.notification)+' · Hue: '+esc(r.hue)+'</p>'}
async function refresh(){try{const response=await fetch("/api/status");if(!response.ok)throw Error("Could not load dashboard");
const d=await response.json();token=d.token;busy=d.running;
document.getElementById("schedule").textContent="Nightly at "+d.time+" · "+d.timezone;
if(!configured){const b=document.getElementById("buttons");const all=document.createElement("button");all.textContent="Check both coops";all.onclick=()=>check(null);b.append(all);
d.coops.forEach(c=>{const el=document.createElement("button");el.textContent="Check "+c.name;el.onclick=()=>check(c.id);b.append(el)});configured=true;}
document.querySelectorAll("button").forEach(b=>b.disabled=busy);
document.getElementById("running").textContent=busy?"Check running — capturing images and counting…":"";
document.getElementById("error").textContent=d.error||"";
const list=document.getElementById("history");list.innerHTML='<option value="">Latest check</option>'+d.history.map(r=>'<option value="'+r.id+'">'+esc(r.created)+' · '+esc(label(r.status))+'</option>').join("");
list.value=selected||"";render(selected?d.history.find(r=>r.id===Number(selected)):d.history[0]);
}catch(e){document.getElementById("error").textContent=e.message}}
document.getElementById("history").onchange=e=>{selected=e.target.value||null;refresh()};
refresh();setInterval(refresh,4000);
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def send(self, status, body, content_type="application/json"):
        payload = json.dumps(body).encode() if content_type=="application/json" else body
        self.send_response(status)
        self.send_header("Content-Type",content_type)
        self.send_header("Content-Length",str(len(payload)))
        self.send_header("Cache-Control","no-store")
        self.send_header("X-Content-Type-Options","nosniff")
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        path = unquote(urlsplit(self.path).path)
        if path=="/":
            return self.send(200,PAGE.encode(),"text/html; charset=utf-8")
        if path=="/api/status":
            with STATE_LOCK:
                state = dict(STATE)
            coops = [{"id":c["id"],"name":c["name"],"expected":c["expected"]}
                     for c in counter.load_coops()]
            return self.send(200,{**state,"token":TOKEN,"coops":coops,"history":history(),
                "time":os.environ.get("CHECK_TIME","22:00"),"timezone":str(ZONE)})
        if path.startswith("/images/"):
            parts=path.split("/")
            if len(parts)!=5 or not parts[2].startswith("run-") or not parts[3].startswith("coop-") or not parts[4].startswith("frame-") or not parts[4].endswith(".jpg"):
                return self.send(404,{"error":"Image not found"})
            file = (DATA / parts[2] / parts[3] / parts[4]).resolve()
            if not file.is_relative_to(DATA.resolve()) or not file.is_file():
                return self.send(404,{"error":"Image not found"})
            return self.send(200,file.read_bytes(),"image/jpeg")
        self.send(404,{"error":"Not found"})

    def do_POST(self):
        if self.path not in ("/api/check", "/api/hue/off"):
            return self.send(404,{"error":"Not found"})
        if self.headers.get("X-Check-Token")!=TOKEN:
            return self.send(403,{"error":"Refresh the dashboard and try again"})
        if self.path == "/api/hue/off":
            # Prevent an in-progress check from immediately overwriting the off command.
            if not MUTEX.acquire(blocking=False):
                return self.send(409, {"error": "Wait for the running check to finish"})
            try:
                outcome = counter.hue_off()
                return self.send(200, {"hue": outcome})
            except RuntimeError as exc:
                return self.send(502, {"error": str(exc)})
            finally:
                MUTEX.release()
        try:
            length=int(self.headers.get("Content-Length","0"))
            if not 0 < length <= 1024:
                raise ValueError()
            body=json.loads(self.rfile.read(length))
            coop=body.get("coop")
            if coop is not None and (type(coop) is not int or coop not in [c["id"] for c in counter.load_coops()]):
                raise ValueError()
        except (ValueError,AttributeError):
            return self.send(400,{"error":"Invalid coop"})
        if not start(coop):
            return self.send(409,{"error":"A check is already running"})
        self.send(202,{"started":True})


def main():
    DATA.mkdir(parents=True,exist_ok=True)
    counter.load_coops()
    db=counter.connect(DATA)
    db.close()
    # Validate time before launching background scheduler.
    dt.time(*map(int,os.environ.get("CHECK_TIME","22:00").split(":")))
    threading.Thread(target=scheduler,daemon=True).start()
    port=int(os.environ.get("WEB_PORT","8080"))
    LOG.info("Dashboard listening on port %s",port)
    ThreadingHTTPServer(("0.0.0.0",port),Handler).serve_forever()


if __name__=="__main__":
    logging.basicConfig(level=logging.INFO,format="%(asctime)s %(levelname)s %(message)s")
    main()
