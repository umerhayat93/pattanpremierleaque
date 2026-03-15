import os, json, sqlite3, time, queue, threading, random, string
from flask import Flask, request, jsonify, send_from_directory, Response

app = Flask(__name__, static_folder='static')

# Render safe DB path
DB_PATH = os.environ.get('DB_PATH', os.path.join(os.getcwd(), 'ppl.db'))

ADMIN_USER = 'ppl2026'
ADMIN_PASS = 'ppl@2620'


# ─────────────────────────────────────────────
# SSE broadcaster
# ─────────────────────────────────────────────

_queues = []
_q_lock = threading.Lock()

def broadcast(data):
    msg = "data: " + json.dumps(data) + "\n\n"
    with _q_lock:
        dead = []
        for q in _queues:
            try:
                q.put_nowait(msg)
            except:
                dead.append(q)
        for q in dead:
            _queues.remove(q)


# ─────────────────────────────────────────────
# Database
# ─────────────────────────────────────────────

def get_db():

    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

    conn = sqlite3.connect(
        DB_PATH,
        check_same_thread=False   # FIX for gunicorn
    )

    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")

    return conn


def init_db():

    with get_db() as db:

        db.executescript("""

CREATE TABLE IF NOT EXISTS groups_(
id TEXT PRIMARY KEY,
name TEXT NOT NULL,
color TEXT DEFAULT 'gold',
created INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS teams(
id TEXT PRIMARY KEY,
name TEXT NOT NULL,
emoji TEXT DEFAULT '?',
captain TEXT DEFAULT '',
grp TEXT DEFAULT '',
created INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS matches_(
id TEXT PRIMARY KEY,
stage TEXT DEFAULT 'group',
grp TEXT DEFAULT '',
no TEXT DEFAULT '',
t1 TEXT NOT NULL,
t2 TEXT NOT NULL,
date_ TEXT DEFAULT '',
time_ TEXT DEFAULT '',
year_ INTEGER DEFAULT 2026,
venue TEXT DEFAULT '',
status TEXT DEFAULT 'upcoming',
result TEXT DEFAULT '',
s1 TEXT DEFAULT '',
s2 TEXT DEFAULT '',
overs INTEGER DEFAULT 16,
highlights TEXT DEFAULT '{}',
inn1 TEXT DEFAULT '{}',
created INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS players(
id TEXT PRIMARY KEY,
name TEXT NOT NULL,
emoji TEXT DEFAULT '?',
team TEXT DEFAULT '',
role TEXT DEFAULT 'batting',
runs INTEGER DEFAULT 0,
wickets INTEGER DEFAULT 0,
sr REAL DEFAULT 0,
best TEXT DEFAULT '',
created INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS polls(
id TEXT PRIMARY KEY,
type_ TEXT DEFAULT 'Poll',
question TEXT NOT NULL,
options TEXT DEFAULT '[]',
votes TEXT DEFAULT '[]',
voted_by TEXT DEFAULT '{}',
created INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS ann(
id INTEGER PRIMARY KEY AUTOINCREMENT,
content TEXT NOT NULL,
created INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS rules_(
id INTEGER PRIMARY KEY AUTOINCREMENT,
content TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS live_(
id INTEGER PRIMARY KEY CHECK(id=1),
data TEXT DEFAULT 'null'
);

INSERT OR IGNORE INTO live_(id,data) VALUES(1,'null');

""")

        db.commit()


init_db()


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def uid():
    return "id" + str(int(time.time()*1000)) + ''.join(random.choices(string.ascii_lowercase, k=4))


def ok(data=None):
    return jsonify({"ok": True, "data": data})


def err(msg, code=400):
    return jsonify({"ok": False, "error": msg}), code


def rows(rows):
    return [dict(r) for r in rows]


def check_admin():

    d = request.get_json(silent=True) or {}

    u = d.get('user') or request.headers.get("X-Admin-User")
    p = d.get('pass') or request.headers.get("X-Admin-Pass")

    return u == ADMIN_USER and p == ADMIN_PASS


# ─────────────────────────────────────────────
# Static
# ─────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory("static", "index.html")


@app.route("/manifest.json")
def manifest():
    return send_from_directory("static", "manifest.json")


@app.route("/sw.js")
def sw():
    return send_from_directory("static", "sw.js")


@app.route("/icons/<path:f>")
def icons(f):
    return send_from_directory("static/icons", f)


# ─────────────────────────────────────────────
# Login
# ─────────────────────────────────────────────

@app.route("/api/login", methods=["POST"])
def login():

    d = request.get_json()

    if d.get("user") == ADMIN_USER and d.get("pass") == ADMIN_PASS:
        return ok({"admin": True})

    return err("Invalid credentials", 401)


# ─────────────────────────────────────────────
# Groups
# ─────────────────────────────────────────────

@app.route("/api/groups")
def groups():

    with get_db() as db:
        r = db.execute("SELECT * FROM groups_ ORDER BY created").fetchall()

    return ok(rows(r))


@app.route("/api/groups", methods=["POST"])
def save_group():

    if not check_admin():
        return err("Unauthorized", 401)

    d = request.json

    name = d.get("name")

    gid = d.get("id") or uid()

    with get_db() as db:

        db.execute(
            "INSERT OR REPLACE INTO groups_ VALUES(?,?,?,?)",
            (gid, name, d.get("color", "gold"), int(time.time()))
        )

        db.commit()

    broadcast({"type": "groups"})

    return ok({"id": gid})


# ─────────────────────────────────────────────
# Teams
# ─────────────────────────────────────────────

@app.route("/api/teams")
def teams():

    with get_db() as db:
        r = db.execute("SELECT * FROM teams ORDER BY created").fetchall()

    return ok(rows(r))


@app.route("/api/teams", methods=["POST"])
def save_team():

    if not check_admin():
        return err("Unauthorized", 401)

    d = request.json

    tid = d.get("id") or uid()

    with get_db() as db:

        db.execute(
            "INSERT OR REPLACE INTO teams VALUES(?,?,?,?,?,?)",
            (
                tid,
                d.get("name"),
                d.get("emoji", "?"),
                d.get("captain", ""),
                d.get("grp", ""),
                int(time.time())
            )
        )

        db.commit()

    broadcast({"type": "teams"})

    return ok({"id": tid})


# ─────────────────────────────────────────────
# Matches
# ─────────────────────────────────────────────

@app.route("/api/matches")
def matches():

    with get_db() as db:
        r = db.execute("SELECT * FROM matches_ ORDER BY date_,time_").fetchall()

    return ok(rows(r))


@app.route("/api/matches", methods=["POST"])
def save_match():

    if not check_admin():
        return err("Unauthorized", 401)

    d = request.json

    mid = d.get("id") or uid()

    with get_db() as db:

        db.execute(
            "INSERT OR REPLACE INTO matches_ VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                mid,
                d.get("stage","group"),
                d.get("grp",""),
                d.get("no",""),
                d.get("t1"),
                d.get("t2"),
                d.get("date_",""),
                d.get("time_",""),
                2026,
                d.get("venue",""),
                "upcoming",
                "",
                "",
                "",
                16,
                "{}",
                "{}",
                int(time.time())
            )
        )

        db.commit()

    broadcast({"type":"matches"})

    return ok({"id":mid})


# ─────────────────────────────────────────────
# Announcements
# ─────────────────────────────────────────────

@app.route("/api/ann")
def ann():

    with get_db() as db:
        r = db.execute("SELECT * FROM ann ORDER BY id DESC").fetchall()

    return ok(rows(r))


@app.route("/api/ann", methods=["POST"])
def add_ann():

    if not check_admin():
        return err("Unauthorized",401)

    d = request.json

    with get_db() as db:

        db.execute(
            "INSERT INTO ann(content,created) VALUES(?,?)",
            (d.get("content"), int(time.time()))
        )

        db.commit()

    broadcast({"type":"ann"})

    return ok()


# ─────────────────────────────────────────────
# Rules
# ─────────────────────────────────────────────

@app.route("/api/rules")
def rules():

    with get_db() as db:
        r = db.execute("SELECT * FROM rules_").fetchall()

    return ok(rows(r))


@app.route("/api/rules", methods=["POST"])
def add_rule():

    if not check_admin():
        return err("Unauthorized",401)

    d = request.json

    with get_db() as db:

        db.execute(
            "INSERT INTO rules_(content) VALUES(?)",
            (d.get("content"),)
        )

        db.commit()

    broadcast({"type":"rules"})

    return ok()


# ─────────────────────────────────────────────
# Polls
# ─────────────────────────────────────────────

@app.route("/api/polls")
def polls():

    with get_db() as db:
        r = db.execute("SELECT * FROM polls ORDER BY created DESC").fetchall()

    return ok(rows(r))


# ─────────────────────────────────────────────
# Live
# ─────────────────────────────────────────────

@app.route("/api/live")
def live():

    with get_db() as db:
        r = db.execute("SELECT data FROM live_ WHERE id=1").fetchone()

    if r and r["data"]:
        return ok(json.loads(r["data"]))

    return ok(None)


# ─────────────────────────────────────────────

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
