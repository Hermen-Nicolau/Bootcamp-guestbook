"""Tanzu Bootcamp guestbook.

Each student pushes this app to their own space and binds it to the same
Postgres service instance (created from the marketplace and shared into
every space). Visitors add their name and hometown; every app reads the
same table, so everyone sees everyone else's entries.

Endpoints:
  /              guestbook page (polls /api/entries every 3 seconds)
  /api/entries   GET: latest entries as JSON; POST {"name","hometown"}: add one
  /db            JSON database check
  /health        liveness check: always 200 while the process is up
"""
import json
import os
import socket
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlparse

import pg8000.native

PORT = int(os.environ.get("PORT", "8080"))
APP = json.loads(os.environ.get("VCAP_APPLICATION", "{}"))
INSTANCE = os.environ.get("CF_INSTANCE_INDEX", "local")
SPACE = APP.get("space_name", "local")
APP_NAME = APP.get("application_name", "bootcamp-app")
MAX_LEN = 60
_table_ready = threading.Event()


def log(msg):
    # Logs go to stdout so Loggregator picks them up (cf logs).
    print(f"[instance {INSTANCE}] {msg}", flush=True)


def find_postgres():
    """Return (service_name, connection kwargs) from VCAP_SERVICES, or (None, None)."""
    services = json.loads(os.environ.get("VCAP_SERVICES", "{}"))
    for offering, instances in services.items():
        for svc in instances:
            creds = svc.get("credentials", {})
            uri = creds.get("uri") or creds.get("url") or ""
            if not uri and creds.get("jdbcUrl"):
                uri = creds["jdbcUrl"].replace("jdbc:", "", 1)
            if uri.split(":", 1)[0] in ("postgres", "postgresql"):
                u = urlparse(uri)
                return svc.get("name", offering), {
                    "host": u.hostname,
                    "port": u.port or 5432,
                    "database": u.path.lstrip("/").split("?")[0],
                    "user": unquote(u.username or creds.get("user") or creds.get("username") or ""),
                    "password": unquote(u.password or creds.get("password") or ""),
                }
            host = creds.get("hostname") or creds.get("host") or (creds.get("hosts") or [None])[0]
            if host:
                return svc.get("name", offering), {
                    "host": host,
                    "port": int(creds.get("port", 5432)),
                    "database": creds.get("name") or creds.get("database") or creds.get("db"),
                    "user": creds.get("username") or creds.get("user"),
                    "password": creds.get("password"),
                }
    return None, None


class NotBound(Exception):
    pass


def connect():
    name, args = find_postgres()
    if not args:
        raise NotBound("No Postgres service bound. Run cf bind-service, then cf restart.")
    conn = pg8000.native.Connection(timeout=5, **args)
    if not _table_ready.is_set():
        conn.run("CREATE TABLE IF NOT EXISTS bootcamp_guestbook ("
                 "id SERIAL PRIMARY KEY, name TEXT NOT NULL, hometown TEXT NOT NULL, "
                 "app TEXT, space TEXT, instance TEXT, created_at TIMESTAMPTZ DEFAULT now())")
        _table_ready.set()
    return name, args, conn


def list_entries():
    _, _, conn = connect()
    try:
        rows = conn.run("SELECT id, name, hometown, space, instance, created_at "
                        "FROM bootcamp_guestbook ORDER BY id DESC LIMIT 200")
        total = conn.run("SELECT count(*) FROM bootcamp_guestbook")[0][0]
    finally:
        conn.close()
    return {"total": total, "entries": [
        {"id": r[0], "name": r[1], "hometown": r[2], "space": r[3], "instance": r[4],
         "created_at": r[5].astimezone(timezone.utc).strftime("%H:%M:%S")} for r in rows]}


def add_entry(name, hometown):
    _, _, conn = connect()
    try:
        conn.run("INSERT INTO bootcamp_guestbook (name, hometown, app, space, instance) "
                 "VALUES (:n, :h, :a, :s, :i)", n=name, h=hometown, a=APP_NAME, s=SPACE, i=str(INSTANCE))
    finally:
        conn.close()


def check_db():
    try:
        name, args, conn = connect()
        try:
            version = conn.run("SELECT version()")[0][0].split(",")[0]
            total = conn.run("SELECT count(*) FROM bootcamp_guestbook")[0][0]
        finally:
            conn.close()
        return {"bound": True, "ok": True, "service": name, "host": args["host"],
                "database": args["database"], "version": version, "guestbook_entries": total}
    except NotBound as exc:
        return {"bound": False, "ok": False, "message": str(exc)}
    except Exception as exc:
        name, args = find_postgres()
        log(f"database error: {exc!r}")
        return {"bound": True, "ok": False, "service": name, "host": (args or {}).get("host"),
                "message": f"{type(exc).__name__}: {exc}"}


PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>Bootcamp guestbook</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
body{font-family:system-ui,sans-serif;max-width:760px;margin:32px auto;padding:0 16px;color:#222}
.meta{color:#555;font-size:14px}.meta code{background:#f3f3f3;padding:1px 4px}
form{display:flex;gap:8px;flex-wrap:wrap;margin:20px 0}input{flex:1;min-width:160px;padding:8px;font-size:15px}
button{padding:8px 16px;font-size:15px;cursor:pointer}
.status{border-radius:6px;padding:10px 12px;margin:12px 0;font-size:14px}
.ok{background:#e7f6ec;border:1px solid #2e7d4f}.bad{background:#fdecea;border:1px solid #b3261e}
table{width:100%;border-collapse:collapse;font-size:14px}th,td{text-align:left;padding:6px 8px;border-bottom:1px solid #eee}
tr.new{animation:flash 2s}@keyframes flash{from{background:#fff3b0}to{background:transparent}}
</style></head><body>
<h1>Tanzu Bootcamp guestbook</h1>
<p class="meta">App <code>__APP__</code> &middot; space <code>__SPACE__</code> &middot; this page was served by instance <code>__INSTANCE__</code></p>
<form id="f"><input id="name" placeholder="Your name" maxlength="60" required>
<input id="hometown" placeholder="Your hometown" maxlength="60" required><button>Sign</button></form>
<div id="status" class="status">Loading...</div>
<table><thead><tr><th>Name</th><th>Hometown</th><th>Signed from space</th><th>Instance</th><th>Time (UTC)</th></tr></thead>
<tbody id="rows"></tbody></table>
<script>
let seen = new Set(), first = true;
function cell(t){const td=document.createElement('td');td.textContent=t;return td}
async function load(){
  try{
    const r = await fetch('/api/entries'); const d = await r.json();
    const s = document.getElementById('status');
    if(!r.ok){ s.className='status bad'; s.textContent=d.message; return; }
    s.className='status ok';
    s.textContent = d.total + ' entries from the shared database \\u00b7 last answer from instance ' + d.served_by + ' (refreshes every 3 s)';
    const tb = document.getElementById('rows'); tb.innerHTML='';
    for(const e of d.entries){
      const tr=document.createElement('tr');
      if(!first && !seen.has(e.id)) tr.className='new';
      seen.add(e.id);
      [e.name,e.hometown,e.space,e.instance,e.created_at].forEach(v=>tr.appendChild(cell(v)));
      tb.appendChild(tr);
    }
    first=false;
  }catch(err){ document.getElementById('status').textContent='Cannot reach the app: '+err; }
}
document.getElementById('f').addEventListener('submit', async ev=>{
  ev.preventDefault();
  const body = JSON.stringify({name:document.getElementById('name').value, hometown:document.getElementById('hometown').value});
  const r = await fetch('/api/entries',{method:'POST',headers:{'Content-Type':'application/json'},body});
  if(r.ok){ document.getElementById('f').reset(); } else { const d=await r.json(); alert(d.message); }
  load();
});
load(); setInterval(load, 3000);
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json"):
        data = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _json(self, code, obj):
        self._send(code, json.dumps(obj, indent=2, default=str))

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/health":
            return self._send(200, "ok", "text/plain")
        if path == "/db":
            r = check_db()
            return self._json(200 if r["ok"] else 503, r)
        if path == "/api/entries":
            try:
                d = list_entries()
                d["served_by"] = str(INSTANCE)
                return self._json(200, d)
            except NotBound as exc:
                return self._json(503, {"message": str(exc)})
            except Exception as exc:
                log(f"database error: {exc!r}")
                return self._json(503, {"message": f"Database error: {type(exc).__name__}: {exc}"})
        if path == "/":
            page = (PAGE.replace("__APP__", APP_NAME).replace("__SPACE__", SPACE)
                    .replace("__INSTANCE__", f"{INSTANCE} ({socket.gethostname()})"))
            return self._send(200, page, "text/html; charset=utf-8")
        self._send(404, "not found", "text/plain")

    def do_POST(self):
        if self.path.split("?")[0] != "/api/entries":
            return self._send(404, "not found", "text/plain")
        try:
            length = min(int(self.headers.get("Content-Length", 0)), 4096)
            data = json.loads(self.rfile.read(length) or b"{}")
            name = str(data.get("name", "")).strip()[:MAX_LEN]
            hometown = str(data.get("hometown", "")).strip()[:MAX_LEN]
        except (ValueError, TypeError):
            return self._json(400, {"message": "Send JSON with name and hometown."})
        if not name or not hometown:
            return self._json(400, {"message": "Name and hometown are both required."})
        try:
            add_entry(name, hometown)
        except NotBound as exc:
            return self._json(503, {"message": str(exc)})
        except Exception as exc:
            log(f"database error: {exc!r}")
            return self._json(503, {"message": f"Database error: {type(exc).__name__}: {exc}"})
        log(f"new guestbook entry: {name} from {hometown}")
        self._json(201, {"ok": True})

    def log_message(self, fmt, *args):
        pass  # the router already logs every request (RTR lines in cf logs)


if __name__ == "__main__":
    name, _ = find_postgres()
    log(f"starting on port {PORT}; postgres service bound: {name or 'none'}")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
