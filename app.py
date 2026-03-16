import os, json, sqlite3, time, queue, threading, random, string
from flask import Flask, request, jsonify, send_from_directory, Response

app = Flask(__name__, static_folder='static')
DB_PATH = os.environ.get('DB_PATH', 
os.path.join(os.getcwd(), 'ppl.db'))
ADMIN_USER = 'ppl2026'
ADMIN_PASS = 'ppl@2620'

# ── SSE broadcaster ────────────────────────────────────────────
_queues = []
_q_lock = threading.Lock()

def broadcast(data):
    msg = "data: " + json.dumps(data) + "\n\n"
    with _q_lock:
        dead = []
        for q in _queues:
            try: q.put_nowait(msg)
            except: dead.append(q)
        for q in dead:
            _queues.remove(q)

# ── Database setup ─────────────────────────────────────────────
def get_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

def init_db():
    with get_db() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS groups_(
            id TEXT PRIMARY KEY, name TEXT NOT NULL,
            color TEXT DEFAULT 'gold', created INTEGER DEFAULT 0);

        CREATE TABLE IF NOT EXISTS teams(
            id TEXT PRIMARY KEY, name TEXT NOT NULL,
            emoji TEXT DEFAULT '?', captain TEXT DEFAULT '',
            grp TEXT DEFAULT '', created INTEGER DEFAULT 0);

        CREATE TABLE IF NOT EXISTS squads(
            id TEXT PRIMARY KEY, team_id TEXT NOT NULL,
            name TEXT NOT NULL, role TEXT DEFAULT 'bat',
            created INTEGER DEFAULT 0);

        CREATE TABLE IF NOT EXISTS matches_(
            id TEXT PRIMARY KEY, stage TEXT DEFAULT 'group',
            grp TEXT DEFAULT '', no TEXT DEFAULT '',
            t1 TEXT NOT NULL, t2 TEXT NOT NULL,
            date_ TEXT DEFAULT '', time_ TEXT DEFAULT '',
            year_ INTEGER DEFAULT 2026,
            venue TEXT DEFAULT 'Pattan Cricket Ground',
            status TEXT DEFAULT 'upcoming', result TEXT DEFAULT '',
            s1 TEXT DEFAULT '', s2 TEXT DEFAULT '',
            overs INTEGER DEFAULT 10,
            highlights TEXT DEFAULT '{}',
            inn1 TEXT DEFAULT '{}',
            created INTEGER DEFAULT 0);

        CREATE TABLE IF NOT EXISTS players(
            id TEXT PRIMARY KEY, name TEXT NOT NULL,
            emoji TEXT DEFAULT '?', team TEXT DEFAULT '',
            role TEXT DEFAULT 'batting', runs INTEGER DEFAULT 0,
            wickets INTEGER DEFAULT 0, sr REAL DEFAULT 0,
            best TEXT DEFAULT '', created INTEGER DEFAULT 0);

        CREATE TABLE IF NOT EXISTS polls(
            id TEXT PRIMARY KEY, type_ TEXT DEFAULT 'Poll',
            question TEXT NOT NULL, options TEXT DEFAULT '[]',
            votes TEXT DEFAULT '[]', voted_by TEXT DEFAULT '{}',
            created INTEGER DEFAULT 0);

        CREATE TABLE IF NOT EXISTS orgs(
            id TEXT PRIMARY KEY, name TEXT NOT NULL,
            role TEXT DEFAULT '', emoji TEXT DEFAULT '?',
            since TEXT DEFAULT '', created INTEGER DEFAULT 0);

        CREATE TABLE IF NOT EXISTS rules_(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content TEXT NOT NULL);

        CREATE TABLE IF NOT EXISTS ann(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content TEXT NOT NULL, created INTEGER DEFAULT 0);

        CREATE TABLE IF NOT EXISTS gallery(
            id TEXT PRIMARY KEY, emoji TEXT DEFAULT '?',
            label TEXT DEFAULT '', cat TEXT DEFAULT 'match',
            created INTEGER DEFAULT 0);

        CREATE TABLE IF NOT EXISTS live_(
            id INTEGER PRIMARY KEY CHECK(id=1),
            data TEXT DEFAULT 'null');

        INSERT OR IGNORE INTO live_(id, data) VALUES(1, 'null');
        """)

init_db()

# ── Helpers ────────────────────────────────────────────────────
def uid():
    return 'id' + str(int(time.time()*1000)) + ''.join(random.choices(string.ascii_lowercase, k=4))

def ok(data=None):
    return jsonify({'ok': True, 'data': data})

def err(msg, code=400):
    return jsonify({'ok': False, 'error': msg}), code

def rows_to_list(rows):
    return [dict(r) for r in rows]

def check_admin():
    # Only read from headers — never consume the request body here
    # Frontend sends X-Admin-User / X-Admin-Pass headers on all admin calls
    u = request.headers.get('X-Admin-User','')
    p = request.headers.get('X-Admin-Pass','')
    return u == ADMIN_USER and p == ADMIN_PASS

# ── Static files ───────────────────────────────────────────────
@app.route('/')
def index():
    return send_from_directory('static', 'index.html')

@app.route('/manifest.json')
def manifest():
    return send_from_directory('static', 'manifest.json')

@app.route('/sw.js')
def sw():
    return send_from_directory('static', 'sw.js')

@app.route('/icons/<path:f>')
def icons(f):
    return send_from_directory('static/icons', f)

@app.route('/api/stream')
def stream():
    q = queue.Queue(maxsize=100)
    with _q_lock:
        _queues.append(q)
    def gen():
        try:
            yield 'data: {"type":"connected"}\n\n'
            while True:
                try:
                    yield q.get(timeout=25)
                except queue.Empty:
                    yield 'data: {"type":"ping"}\n\n'
        except GeneratorExit:
            pass
        finally:
            with _q_lock:
                if q in _queues: _queues.remove(q)
    return Response(gen(), mimetype='text/event-stream',
        headers={'Cache-Control':'no-cache','X-Accel-Buffering':'no',
                 'Access-Control-Allow-Origin':'*'})

# ── Auth ───────────────────────────────────────────────────────
@app.route('/api/login', methods=['POST'])
def login():
    d = request.get_json(silent=True) or {}
    if d.get('user') == ADMIN_USER and d.get('pass') == ADMIN_PASS:
        return ok({'admin': True})
    return err('Invalid credentials', 401)

# ── Groups ─────────────────────────────────────────────────────
@app.route('/api/groups', methods=['GET'])
def get_groups():
    with get_db() as db:
        rows = db.execute("SELECT * FROM groups_ ORDER BY created").fetchall()
    return ok(rows_to_list(rows))

@app.route('/api/groups', methods=['POST'])
def save_group():
    if not check_admin(): return err('Unauthorized', 401)
    d = request.get_json(silent=True) or {}
    name = (d.get('name') or '').strip()
    if not name: return err('Name required')
    gid = d.get('id') or uid()
    with get_db() as db:
        db.execute("INSERT OR REPLACE INTO groups_ VALUES(?,?,?,?)",
            (gid, name, d.get('color','gold'), int(time.time())))
    broadcast({'type':'groups'})
    return ok({'id': gid})

@app.route('/api/groups/<gid>', methods=['DELETE'])
def delete_group(gid):
    if not check_admin(): return err('Unauthorized', 401)
    with get_db() as db:
        db.execute("DELETE FROM groups_ WHERE id=?", (gid,))
        db.execute("UPDATE teams SET grp='' WHERE grp=?", (gid,))
    broadcast({'type':'groups'})
    broadcast({'type':'teams'})
    return ok()

# ── Teams ──────────────────────────────────────────────────────
@app.route('/api/teams', methods=['GET'])
def get_teams():
    with get_db() as db:
        rows = db.execute("SELECT * FROM teams ORDER BY created").fetchall()
    return ok(rows_to_list(rows))

@app.route('/api/teams', methods=['POST'])
def save_team():
    if not check_admin(): return err('Unauthorized', 401)
    d = request.get_json(silent=True) or {}
    name = (d.get('name') or '').strip()
    if not name: return err('Name required')
    tid = d.get('id') or uid()
    with get_db() as db:
        db.execute("INSERT OR REPLACE INTO teams VALUES(?,?,?,?,?,?)",
            (tid, name, d.get('emoji','?'), d.get('captain',''),
             d.get('grp',''), int(time.time())))
    broadcast({'type':'teams'})
    return ok({'id': tid})

@app.route('/api/teams/<tid>', methods=['DELETE'])
def delete_team(tid):
    if not check_admin(): return err('Unauthorized', 401)
    with get_db() as db:
        db.execute("DELETE FROM teams WHERE id=?", (tid,))
    broadcast({'type':'teams'})
    return ok()

# ── Squads ─────────────────────────────────────────────────────
@app.route('/api/squads/<tid>', methods=['GET'])
def get_squad(tid):
    with get_db() as db:
        rows = db.execute("SELECT * FROM squads WHERE team_id=? ORDER BY created", (tid,)).fetchall()
    return ok(rows_to_list(rows))

@app.route('/api/squads/<tid>', methods=['POST'])
def add_squad(tid):
    if not check_admin(): return err('Unauthorized', 401)
    d = request.get_json(silent=True) or {}
    name = (d.get('name') or '').strip()
    if not name: return err('Name required')
    pid = uid()
    with get_db() as db:
        db.execute("INSERT INTO squads VALUES(?,?,?,?,?)",
            (pid, tid, name, d.get('role','bat'), int(time.time())))
    return ok({'id': pid})

@app.route('/api/squads/<tid>/<pid>', methods=['DELETE'])
def del_squad(tid, pid):
    if not check_admin(): return err('Unauthorized', 401)
    with get_db() as db:
        db.execute("DELETE FROM squads WHERE id=? AND team_id=?", (pid, tid))
    return ok()

# ── Matches ────────────────────────────────────────────────────
@app.route('/api/matches', methods=['GET'])
def get_matches():
    with get_db() as db:
        rows = db.execute("SELECT * FROM matches_ ORDER BY date_, time_").fetchall()
    result = []
    for r in rows:
        d = dict(r)
        try: d['highlights'] = json.loads(d.get('highlights') or '{}')
        except: d['highlights'] = {}
        try: d['inn1'] = json.loads(d.get('inn1') or '{}')
        except: d['inn1'] = {}
        result.append(d)
    return ok(result)

@app.route('/api/matches', methods=['POST'])
def save_match():
    if not check_admin(): return err('Unauthorized', 401)
    d = request.get_json(silent=True) or {}
    if not d.get('t1') or not d.get('t2'): return err('Teams required')
    mid = d.get('id') or uid()
    with get_db() as db:
        db.execute("INSERT OR REPLACE INTO matches_ VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (mid, d.get('stage','group'), d.get('grp',''), d.get('no',''),
             d['t1'], d['t2'], d.get('date_',''), d.get('time_',''),
             int(d.get('year_',2026)), d.get('venue','Pattan Cricket Ground'),
             d.get('status','upcoming'), d.get('result',''),
             d.get('s1',''), d.get('s2',''), 10,
             json.dumps(d.get('highlights',{})),
             json.dumps(d.get('inn1',{})),
             int(time.time())))
    broadcast({'type':'matches'})
    return ok({'id': mid})

@app.route('/api/matches/<mid>', methods=['DELETE'])
def delete_match(mid):
    if not check_admin(): return err('Unauthorized', 401)
    with get_db() as db:
        db.execute("DELETE FROM matches_ WHERE id=?", (mid,))
    broadcast({'type':'matches'})
    return ok()

@app.route('/api/matches/<mid>/finish', methods=['POST'])
def finish_match(mid):
    if not check_admin(): return err('Unauthorized', 401)
    d = request.get_json(silent=True) or {}
    with get_db() as db:
        db.execute("UPDATE matches_ SET status='completed',result=?,s1=?,s2=?,highlights=? WHERE id=?",
            (d.get('result',''), d.get('s1',''), d.get('s2',''),
             json.dumps(d.get('highlights',{})), mid))
    broadcast({'type':'matches'})
    return ok()

@app.route('/api/matches/<mid>/inn1', methods=['POST'])
def save_inn1(mid):
    if not check_admin(): return err('Unauthorized', 401)
    d = request.get_json(silent=True) or {}
    with get_db() as db:
        db.execute("UPDATE matches_ SET inn1=?,s1=? WHERE id=?",
            (json.dumps(d.get('inn1',{})), d.get('s1',''), mid))
    return ok()

@app.route('/api/matches/<mid>/status', methods=['POST'])
def update_status(mid):
    if not check_admin(): return err('Unauthorized', 401)
    d = request.get_json(silent=True) or {}
    with get_db() as db:
        row = db.execute("SELECT * FROM matches_ WHERE id=?", (mid,)).fetchone()
        if not row: return err('Not found', 404)
        db.execute("UPDATE matches_ SET status=?,result=?,s1=?,s2=? WHERE id=?",
            (d.get('status', row['status']),
             d.get('result', row['result']),
             d.get('s1', row['s1']),
             d.get('s2', row['s2']), mid))
    broadcast({'type':'matches'})
    return ok()

# ── Live scoring ───────────────────────────────────────────────
@app.route('/api/live', methods=['GET'])
def get_live():
    with get_db() as db:
        row = db.execute("SELECT data FROM live_ WHERE id=1").fetchone()
    val = json.loads(row['data']) if row and row['data'] not in ('null', None, '') else None
    return ok(val)

@app.route('/api/live', methods=['PUT'])
def set_live():
    if not check_admin(): return err('Unauthorized', 401)
    d = request.get_json(silent=True)
    with get_db() as db:
        db.execute("UPDATE live_ SET data=? WHERE id=1", (json.dumps(d),))
    broadcast({'type':'live', 'data': d})
    return ok()

@app.route('/api/live', methods=['DELETE'])
def clear_live():
    if not check_admin(): return err('Unauthorized', 401)
    with get_db() as db:
        db.execute("UPDATE live_ SET data='null' WHERE id=1")
    broadcast({'type':'live', 'data': None})
    return ok()

# ── Players ────────────────────────────────────────────────────
@app.route('/api/players', methods=['GET'])
def get_players():
    with get_db() as db:
        rows = db.execute("SELECT * FROM players ORDER BY runs DESC, wickets DESC").fetchall()
    return ok(rows_to_list(rows))

@app.route('/api/players', methods=['POST'])
def save_player():
    if not check_admin(): return err('Unauthorized', 401)
    d = request.get_json(silent=True) or {}
    name = (d.get('name') or '').strip()
    if not name: return err('Name required')
    pid = d.get('id') or uid()
    with get_db() as db:
        db.execute("INSERT OR REPLACE INTO players VALUES(?,?,?,?,?,?,?,?,?,?)",
            (pid, name, d.get('emoji','?'), d.get('team',''),
             d.get('role','batting'), int(d.get('runs',0)),
             int(d.get('wickets',0)), float(d.get('sr',0)),
             d.get('best',''), int(time.time())))
    broadcast({'type':'players'})
    return ok({'id': pid})

@app.route('/api/players/<pid>', methods=['DELETE'])
def delete_player(pid):
    if not check_admin(): return err('Unauthorized', 401)
    with get_db() as db:
        db.execute("DELETE FROM players WHERE id=?", (pid,))
    broadcast({'type':'players'})
    return ok()

# ── Polls ──────────────────────────────────────────────────────
@app.route('/api/polls', methods=['GET'])
def get_polls():
    with get_db() as db:
        rows = db.execute("SELECT * FROM polls ORDER BY created DESC").fetchall()
    result = []
    for r in rows:
        d = dict(r)
        try: d['options'] = json.loads(d.get('options') or '[]')
        except: d['options'] = []
        try: d['votes'] = json.loads(d.get('votes') or '[]')
        except: d['votes'] = []
        try: d['voted_by'] = json.loads(d.get('voted_by') or '{}')
        except: d['voted_by'] = {}
        result.append(d)
    return ok(result)

@app.route('/api/polls', methods=['POST'])
def save_poll():
    if not check_admin(): return err('Unauthorized', 401)
    d = request.get_json(silent=True) or {}
    q = (d.get('question') or '').strip()
    opts = d.get('options', [])
    if not q or len(opts) < 2: return err('Need question and 2+ options')
    pid = uid()
    with get_db() as db:
        db.execute("INSERT INTO polls VALUES(?,?,?,?,?,?,?)",
            (pid, d.get('type_','Poll'), q, json.dumps(opts),
             json.dumps([0]*len(opts)), '{}', int(time.time())))
    broadcast({'type':'polls'})
    return ok({'id': pid})

@app.route('/api/polls/<pid>/vote', methods=['POST'])
def vote(pid):
    d = request.get_json(silent=True) or {}
    voter = (d.get('voter') or '').strip()
    idx = int(d.get('idx', -1))
    if not voter: return err('Voter required')
    with get_db() as db:
        row = db.execute("SELECT * FROM polls WHERE id=?", (pid,)).fetchone()
        if not row: return err('Not found', 404)
        voted_by = json.loads(row['voted_by'] or '{}')
        if voter in voted_by: return err('Already voted')
        votes = json.loads(row['votes'] or '[]')
        if idx < 0 or idx >= len(votes): return err('Bad index')
        votes[idx] += 1
        voted_by[voter] = True
        db.execute("UPDATE polls SET votes=?,voted_by=? WHERE id=?",
            (json.dumps(votes), json.dumps(voted_by), pid))
    broadcast({'type':'polls'})
    return ok()

@app.route('/api/polls/<pid>', methods=['DELETE'])
def delete_poll(pid):
    if not check_admin(): return err('Unauthorized', 401)
    with get_db() as db:
        db.execute("DELETE FROM polls WHERE id=?", (pid,))
    broadcast({'type':'polls'})
    return ok()

# ── Orgs ───────────────────────────────────────────────────────
@app.route('/api/orgs', methods=['GET'])
def get_orgs():
    with get_db() as db:
        rows = db.execute("SELECT * FROM orgs ORDER BY created").fetchall()
    return ok(rows_to_list(rows))

@app.route('/api/orgs', methods=['POST'])
def save_org():
    if not check_admin(): return err('Unauthorized', 401)
    d = request.get_json(silent=True) or {}
    name = (d.get('name') or '').strip()
    if not name: return err('Name required')
    oid = d.get('id') or uid()
    with get_db() as db:
        db.execute("INSERT OR REPLACE INTO orgs VALUES(?,?,?,?,?,?)",
            (oid, name, d.get('role',''), d.get('emoji','?'),
             d.get('since',''), int(time.time())))
    broadcast({'type':'orgs'})
    return ok({'id': oid})

@app.route('/api/orgs/<oid>', methods=['DELETE'])
def delete_org(oid):
    if not check_admin(): return err('Unauthorized', 401)
    with get_db() as db:
        db.execute("DELETE FROM orgs WHERE id=?", (oid,))
    broadcast({'type':'orgs'})
    return ok()

# ── Rules ──────────────────────────────────────────────────────
@app.route('/api/rules', methods=['GET'])
def get_rules():
    with get_db() as db:
        rows = db.execute("SELECT * FROM rules_ ORDER BY id").fetchall()
    return ok([{'id': r['id'], 'content': r['content']} for r in rows])

@app.route('/api/rules', methods=['POST'])
def add_rule():
    if not check_admin(): return err('Unauthorized', 401)
    d = request.get_json(silent=True) or {}
    content = (d.get('content') or '').strip()
    if not content: return err('Content required')
    with get_db() as db:
        cur = db.execute("INSERT INTO rules_(content) VALUES(?)", (content,))
        rid = cur.lastrowid
    broadcast({'type':'rules'})
    return ok({'id': rid})

@app.route('/api/rules/<int:rid>', methods=['DELETE'])
def delete_rule(rid):
    if not check_admin(): return err('Unauthorized', 401)
    with get_db() as db:
        db.execute("DELETE FROM rules_ WHERE id=?", (rid,))
    broadcast({'type':'rules'})
    return ok()

# ── Announcements ──────────────────────────────────────────────
@app.route('/api/ann', methods=['GET'])
def get_ann():
    with get_db() as db:
        rows = db.execute("SELECT * FROM ann ORDER BY created DESC LIMIT 30").fetchall()
    return ok([{'id': r['id'], 'content': r['content']} for r in rows])

@app.route('/api/ann', methods=['POST'])
def add_ann():
    if not check_admin(): return err('Unauthorized', 401)
    d = request.get_json(silent=True) or {}
    content = (d.get('content') or '').strip()
    if not content: return err('Content required')
    with get_db() as db:
        cur = db.execute("INSERT INTO ann(content,created) VALUES(?,?)", (content, int(time.time())))
        aid = cur.lastrowid
    broadcast({'type':'ann'})
    return ok({'id': aid})

@app.route('/api/ann/<int:aid>', methods=['DELETE'])
def delete_ann(aid):
    if not check_admin(): return err('Unauthorized', 401)
    with get_db() as db:
        db.execute("DELETE FROM ann WHERE id=?", (aid,))
    broadcast({'type':'ann'})
    return ok()

# ── Gallery ────────────────────────────────────────────────────
@app.route('/api/gallery', methods=['GET'])
def get_gallery():
    with get_db() as db:
        rows = db.execute("SELECT * FROM gallery ORDER BY created").fetchall()
    return ok(rows_to_list(rows))

@app.route('/api/gallery', methods=['POST'])
def add_gallery():
    if not check_admin(): return err('Unauthorized', 401)
    d = request.get_json(silent=True) or {}
    gid = uid()
    with get_db() as db:
        db.execute("INSERT INTO gallery VALUES(?,?,?,?,?)",
            (gid, d.get('emoji','?'), d.get('label',''),
             d.get('cat','match'), int(time.time())))
    broadcast({'type':'gallery'})
    return ok({'id': gid})

@app.route('/api/gallery/<gid>', methods=['DELETE'])
def delete_gallery(gid):
    if not check_admin(): return err('Unauthorized', 401)
    with get_db() as db:
        db.execute("DELETE FROM gallery WHERE id=?", (gid,))
    broadcast({'type':'gallery'})
    return ok()

# ── Notify ─────────────────────────────────────────────────────
@app.route('/api/notify', methods=['POST'])
def notify():
    if not check_admin(): return err('Unauthorized', 401)
    d = request.get_json(silent=True) or {}
    broadcast({'type':'notification',
               'title': d.get('title','PPL 2026'),
               'body': d.get('body',''),
               'icon': d.get('icon','?')})
    return ok()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)
