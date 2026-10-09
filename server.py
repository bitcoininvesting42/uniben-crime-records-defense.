"""UNIBEN Crime Records & Information System — academic demonstration.

Python 3.10+; standard library only. Run: python server.py
Fictional seed records and demonstration accounts. Not production-ready.
"""
from __future__ import annotations
import csv
from contextlib import closing
import hashlib
import hmac
import io
import json
import os
import secrets
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

BASE = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get('CRIS_DB', BASE / 'crime_records_demo.db'))
HOST = os.environ.get('CRIS_HOST', '0.0.0.0' if os.environ.get('RENDER') else '127.0.0.1')
PORT = int(os.environ.get('CRIS_PORT') or os.environ.get('PORT') or '8080')
PUBLIC_DEMO = os.environ.get('CRIS_PUBLIC_DEMO', '0') == '1'
PROJECT = 'UNIBEN Crime Records & Information System'
DATA_LOCK = threading.RLock()
CURRENT_YEAR = 2026  # Named demonstration period, not inferred from live incidents.
ROLES = {'administrator', 'officer', 'analyst'}
CATEGORIES = {'Theft', 'Burglary', 'Assault', 'Fraud', 'Cybercrime', 'Vandalism', 'Robbery', 'Other'}
PRIORITIES = {'Critical', 'High', 'Medium', 'Low'}
STATUSES = {'Open', 'Under Investigation', 'Pending Review', 'Resolved', 'Closed'}
INVOLVEMENT_ROLES = {'Complainant', 'Witness', 'Subject of allegation', 'Victim'}

class ApiError(Exception):
    def __init__(self, status, message):
        self.status, self.message = status, message
        super().__init__(message)

def utcnow():
    return datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')

def password_hash(password: str, salt: bytes | None = None):
    salt = salt or secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 240_000)
    return f'pbkdf2_sha256$240000${salt.hex()}${dk.hex()}'

def password_ok(password: str, stored: str):
    try:
        algo, iterations, salt, digest = stored.split('$')
        if algo != 'pbkdf2_sha256': return False
        result = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), int(iterations))
        return hmac.compare_digest(result, bytes.fromhex(digest))
    except (ValueError, TypeError):
        return False

def db_connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=10, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA foreign_keys=ON')
    con.execute('PRAGMA busy_timeout=10000')
    return con

def rows(cur):
    return [dict(r) for r in cur.fetchall()]

def required(payload, key, max_length=200):
    val = payload.get(key)
    if not isinstance(val, str) or not val.strip():
        raise ApiError(400, f'{key.replace("_", " ").capitalize()} is required.')
    val = val.strip()
    if len(val) > max_length: raise ApiError(400, f'{key} must be at most {max_length} characters.')
    return val

def optional(payload, key, max_length=200):
    val = payload.get(key, '')
    if val is None: return ''
    if not isinstance(val, str): raise ApiError(400, f'{key} must be text.')
    if len(val.strip()) > max_length: raise ApiError(400, f'{key} must be at most {max_length} characters.')
    return val.strip()

def enum(payload, key, allowed, default=None):
    val = payload.get(key, default)
    if val not in allowed: raise ApiError(400, f'Invalid {key}.')
    return val

def date_field(payload, key):
    val = required(payload, key, 10)
    try: datetime.strptime(val, '%Y-%m-%d')
    except ValueError: raise ApiError(400, f'{key} must be a valid YYYY-MM-DD date.')
    return val

def valid_id(value):
    try: n = int(value)
    except (ValueError, TypeError): raise ApiError(400, 'Invalid record ID.')
    if n < 1: raise ApiError(400, 'Invalid record ID.')
    return n

def ref(kind, pk):
    return f'{kind}-{CURRENT_YEAR}-{pk:04d}'

def log(con, actor, action, target, detail=''):
    con.execute('INSERT INTO audit_log (user_id, action, target, detail, created_at) VALUES (?, ?, ?, ?, ?)',
                (actor, action, target, detail[:500], utcnow()))

def init_db():
    with DATA_LOCK:
        with closing(db_connect()) as con:
            con.executescript('''
            CREATE TABLE IF NOT EXISTS users (
              id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL UNIQUE,
              display_name TEXT NOT NULL, role TEXT NOT NULL, password_hash TEXT NOT NULL,
              active INTEGER NOT NULL DEFAULT 1);
            CREATE TABLE IF NOT EXISTS sessions (
              token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
              csrf TEXT NOT NULL, expires_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS incidents (
              id INTEGER PRIMARY KEY AUTOINCREMENT, reference TEXT UNIQUE,
              category TEXT NOT NULL, occurred_on TEXT NOT NULL, reported_on TEXT NOT NULL,
              location TEXT NOT NULL, summary TEXT NOT NULL, created_by INTEGER REFERENCES users(id),
              created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS case_files (
              id INTEGER PRIMARY KEY AUTOINCREMENT, reference TEXT UNIQUE,
              incident_id INTEGER NOT NULL REFERENCES incidents(id),
              title TEXT NOT NULL, details TEXT NOT NULL DEFAULT '', priority TEXT NOT NULL,
              status TEXT NOT NULL, assigned_to INTEGER REFERENCES users(id),
              created_by INTEGER REFERENCES users(id), created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS people (
              id INTEGER PRIMARY KEY AUTOINCREMENT, reference TEXT UNIQUE,
              full_name TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
              created_by INTEGER REFERENCES users(id), created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS involvements (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              case_id INTEGER NOT NULL REFERENCES case_files(id),
              person_id INTEGER NOT NULL REFERENCES people(id),
              role TEXT NOT NULL, UNIQUE(case_id, person_id, role));
            CREATE TABLE IF NOT EXISTS evidence (
              id INTEGER PRIMARY KEY AUTOINCREMENT, reference TEXT UNIQUE,
              case_id INTEGER NOT NULL REFERENCES case_files(id), item_name TEXT NOT NULL,
              description TEXT NOT NULL DEFAULT '', collected_on TEXT NOT NULL,
              storage_location TEXT NOT NULL, custodian TEXT NOT NULL,
              created_by INTEGER REFERENCES users(id), created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS status_history (
              id INTEGER PRIMARY KEY AUTOINCREMENT, case_id INTEGER NOT NULL REFERENCES case_files(id),
              old_status TEXT, new_status TEXT NOT NULL, reason TEXT NOT NULL,
              changed_by INTEGER REFERENCES users(id), created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS audit_log (
              id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER REFERENCES users(id),
              action TEXT NOT NULL, target TEXT NOT NULL, detail TEXT NOT NULL DEFAULT '',
              created_at TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS idx_case_status ON case_files(status);
            CREATE INDEX IF NOT EXISTS idx_case_incident ON case_files(incident_id);
            CREATE INDEX IF NOT EXISTS idx_incident_category ON incidents(category);
            CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_log(created_at);
            ''')
            if con.execute('SELECT COUNT(*) FROM users').fetchone()[0]: return
            if PUBLIC_DEMO:
                # Hosted demo passwords must be supplied privately in Render environment variables.
                # Never expose the local example passwords when the site is publicly accessible.
                names = ('ADMIN', 'OFFICER', 'ANALYST')
                demo_secrets = {name: os.environ.get('CRIS_' + name + '_PASSWORD', '') for name in names}
                if any(len(value) < 12 for value in demo_secrets.values()):
                    raise RuntimeError('Hosted demo requires CRIS_ADMIN_PASSWORD, CRIS_OFFICER_PASSWORD and CRIS_ANALYST_PASSWORD (12+ chars each).')
                if len(set(demo_secrets.values())) != 3:
                    raise RuntimeError('Hosted demo passwords must be distinct.')
            else:
                demo_secrets = {'ADMIN': 'Admin@2026', 'OFFICER': 'Officer@2026', 'ANALYST': 'Analyst@2026'}
            demo_users = [
              ('admin', 'System Administrator', 'administrator', demo_secrets['ADMIN']),
              ('officer', 'Records Officer', 'officer', demo_secrets['OFFICER']),
              ('analyst', 'Reports Analyst', 'analyst', demo_secrets['ANALYST']),
            ]
            for username, name, role, password in demo_users:
                con.execute('INSERT INTO users (username, display_name, role, password_hash) VALUES (?,?,?,?)',
                            (username, name, role, password_hash(password)))
            incidents = [
                ('Theft','2026-10-01','2026-10-01','Ugbowo, Benin City','Reported loss of an unattended mobile device.'),
                ('Cybercrime','2026-09-29','2026-09-30','Online / Benin City','Complaint of a suspicious online payment request.'),
                ('Burglary','2026-09-26','2026-09-27','Ekosodin, Benin City','Reported unauthorised entry into a vacant office.'),
                ('Assault','2026-09-24','2026-09-24','Uselu, Benin City','Complaint involving an altercation near a commercial area.'),
                ('Fraud','2026-09-20','2026-09-21','Ring Road, Benin City','Reported irregularity in a fictional procurement transaction.'),
                ('Vandalism','2026-09-18','2026-09-19','Ekehuan, Benin City','Reported damage to public-facing signage.'),
                ('Robbery','2026-09-15','2026-09-16','Sapele Road, Benin City','Reported loss of valuables during a roadside incident.'),
                ('Theft','2026-09-11','2026-09-12','New Benin, Benin City','Inventory discrepancy reported at a local shop.'),
                ('Cybercrime','2026-08-28','2026-08-29','Online / Ugbowo','Reported unauthorised access attempt to a fictional account.'),
                ('Assault','2026-08-14','2026-08-14','GRA, Benin City','Dispute between two fictional individuals.'),
                ('Fraud','2026-07-20','2026-07-21','Ikpoba Hill, Benin City','Complaint regarding a fictitious service invoice.'),
                ('Burglary','2026-07-08','2026-07-09','Oluku, Benin City','Reported signs of entry at an unoccupied building.'),
                ('Vandalism','2026-06-18','2026-06-18','Upper Mission, Benin City','Damaged fixtures discovered at a demonstration site.'),
                ('Theft','2026-05-03','2026-05-04','Aduwawa, Benin City','Reported missing equipment from a fictional storeroom.'),
            ]
            for i, data in enumerate(incidents, 1):
                con.execute('INSERT INTO incidents (reference,category,occurred_on,reported_on,location,summary,created_by,created_at) VALUES (?,?,?,?,?,?,?,?)',
                   (ref('INC',i), *data, 2, f'{data[2]}T10:30:00Z'))
            cases = [
                (1,'Missing Device Report','Medium','Open',2),
                (2,'Online Payment Complaint','High','Under Investigation',2),
                (3,'Office Entry Review','High','Pending Review',2),
                (4,'Commercial Area Altercation','Medium','Resolved',2),
                (5,'Procurement Discrepancy','High','Under Investigation',2),
                (6,'Signage Damage Report','Low','Closed',2),
                (7,'Roadside Property Loss','Critical','Under Investigation',2),
                (8,'Retail Inventory Review','Medium','Open',2),
                (9,'Account Access Complaint','Medium','Pending Review',2),
                (10,'Neighbourhood Dispute','Low','Resolved',2),
                (11,'Invoice Complaint','High','Open',2),
                (12,'Building Entry Assessment','Medium','Closed',2),
                (13,'Facility Damage Review','Low','Resolved',2),
                (14,'Equipment Discrepancy','Medium','Resolved',2),
            ]
            for i, (incident, title, priority, status, assigned) in enumerate(cases, 1):
                created = f'{incidents[incident-1][2]}T12:00:00Z'
                con.execute('INSERT INTO case_files (reference,incident_id,title,details,priority,status,assigned_to,created_by,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)',
                    (ref('CASE',i),incident,title,'Synthetic academic demonstration record; no real person is alleged to have committed an offence.',priority,status,assigned,2,created,created))
                con.execute('INSERT INTO status_history (case_id,old_status,new_status,reason,changed_by,created_at) VALUES (?,?,?,?,?,?)',
                    (i,None,'Open','Case registration',2,created))
                if status != 'Open':
                    con.execute('INSERT INTO status_history (case_id,old_status,new_status,reason,changed_by,created_at) VALUES (?,?,?,?,?,?)',
                        (i,'Open',status,'Demo workflow update',2,created))
            demo_people = [('Amina Okoro','Fictional reporting party'),('Tunde Bello','Fictional witness'),('Ifeoma Eze','Fictional complainant'),('David Aigbe','Fictional subject of allegation'),('Zainab Musa','Fictional witness'),('Osas Igbinovia','Fictional complainant')]
            for i,(name,description) in enumerate(demo_people,1):
                con.execute('INSERT INTO people (reference,full_name,description,created_by,created_at) VALUES (?,?,?,?,?)',
                       (ref('PER',i),name,description,2,utcnow()))
            for case_id, person_id, role in [(1,1,'Complainant'),(2,2,'Witness'),(3,3,'Complainant'),(4,4,'Subject of allegation'),(5,5,'Witness'),(7,6,'Victim')]:
                con.execute('INSERT INTO involvements (case_id,person_id,role) VALUES (?,?,?)',(case_id,person_id,role))
            demo_evidence = [(1,'Inventory note','Recorded list of reported items','2026-10-01','Cabinet A-03','Records Officer'),(2,'Transaction log','Illustrative payment reference extract','2026-09-30','Digital Store','Records Officer'),(3,'Photograph record','Non-identifying office entry image','2026-09-27','Secure Archive','Records Officer'),(5,'Invoice copy','Synthetic invoice data','2026-09-21','Digital Store','Records Officer'),(7,'Statement extract','Illustrative statement excerpt','2026-09-16','Cabinet B-02','Records Officer'),(9,'Account activity log','Simulated authentication records','2026-08-29','Digital Store','Records Officer')]
            for i,(case_id,name,description,day,storage,custodian) in enumerate(demo_evidence,1):
                con.execute('INSERT INTO evidence (reference,case_id,item_name,description,collected_on,storage_location,custodian,created_by,created_at) VALUES (?,?,?,?,?,?,?,?,?)',
                    (ref('EVD',i),case_id,name,description,day,storage,custodian,2,utcnow()))
            log(con, 1, 'DEMO_INITIALIZED', 'SYSTEM', 'Fictional demonstration records seeded')
            con.commit()

def query_all(con, sql, params=()): return rows(con.execute(sql, params))

def get_user(con, username):
    r = con.execute('SELECT * FROM users WHERE username=? AND active=1',(username,)).fetchone()
    return dict(r) if r else None

def private_session(con, req):
    cookies = SimpleCookie()
    try: cookies.load(req.headers.get('Cookie', ''))
    except Exception: return None
    if 'cris_session' not in cookies: return None
    token = cookies['cris_session'].value
    hashed = hashlib.sha256(token.encode()).hexdigest()
    r = con.execute('''SELECT s.csrf, s.expires_at, u.id, u.username, u.display_name, u.role
         FROM sessions s JOIN users u ON s.user_id=u.id WHERE s.token_hash=? AND u.active=1''',(hashed,)).fetchone()
    if not r or r['expires_at'] < utcnow(): return None
    return dict(r)

class Handler(BaseHTTPRequestHandler):
    server_version = 'UNIBEN-CRIS-Demo/1.0'
    def log_message(self, fmt, *args):
        if os.environ.get('CRIS_QUIET') != '1': super().log_message(fmt,*args)
    def send_json(self, payload, code=200, headers=None):
        data = json.dumps(payload, ensure_ascii=False, default=str).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Content-Security-Policy',"default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; base-uri 'none'; object-src 'none'")
        if headers:
            for k,v in headers.items(): self.send_header(k,v)
        self.send_header('Content-Length',str(len(data)))
        self.end_headers(); self.wfile.write(data)
    def read_body(self):
        try: length = int(self.headers.get('Content-Length','0'))
        except ValueError: raise ApiError(400,'Invalid request length.')
        if length < 0 or length > 100_000: raise ApiError(413,'Request too large.')
        try: obj = json.loads(self.rfile.read(length) or b'{}')
        except (ValueError,UnicodeError): raise ApiError(400,'Invalid JSON request.')
        if not isinstance(obj,dict): raise ApiError(400,'Expected a JSON object.')
        return obj
    def send_file(self, path, mime):
        if not path.exists(): return self.send_json({'error':'Not found'},404)
        content = path.read_bytes()
        self.send_response(200)
        self.send_header('Content-Type',mime)
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Content-Security-Policy',"default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; base-uri 'none'; object-src 'none'")
        self.send_header('Cache-Control','no-cache')
        self.send_header('Content-Length',str(len(content)))
        self.end_headers(); self.wfile.write(content)
    def do_GET(self): self.serve('GET')
    def do_POST(self): self.serve('POST')
    def do_PATCH(self): self.serve('PATCH')
    def do_OPTIONS(self): self.send_json({'error':'Method not allowed'},405)
    def serve(self, method):
        route = urlparse(self.path)
        if method == 'GET' and route.path == '/api/health':
            return self.send_json({'status':'ok','project':PROJECT})
        if not route.path.startswith('/api/'):
            if method!='GET': return self.send_json({'error':'Method not allowed'},405)
            static = {'/':('index.html','text/html; charset=utf-8'), '/index.html':('index.html','text/html; charset=utf-8'),
                '/styles.css':('styles.css','text/css; charset=utf-8'),'/app.js':('app.js','text/javascript; charset=utf-8'),
                '/favicon.svg':('favicon.svg','image/svg+xml'),
                '/architecture.svg':('architecture.svg','image/svg+xml'),
                '/database-model.svg':('database-model.svg','image/svg+xml')}
            if route.path not in static: return self.send_json({'error':'Not found'},404)
            fn,mime=static[route.path]; return self.send_file(BASE/'static'/fn,mime)
        try:
            with closing(db_connect()) as con:
                return self.api(con,method,route.path,parse_qs(route.query))
        except ApiError as e:
            self.send_json({'error':e.message},e.status)
        except (sqlite3.IntegrityError,sqlite3.OperationalError) as e:
            if os.environ.get('CRIS_DEBUG'): print('SQL:',repr(e))
            self.send_json({'error':'Database constraint or access error.'},409)
        except Exception as e:
            if os.environ.get('CRIS_DEBUG'): print('ERROR:',repr(e))
            self.send_json({'error':'Unexpected server error.'},500)
    def api(self, con, method, path, params):
        sess=private_session(con,self)
        if method=='GET' and path=='/api/session':
            if not sess: return self.send_json({'authenticated':False})
            return self.send_json({'authenticated':True,'user':{k:sess[k] for k in ('id','username','display_name','role')}, 'csrf':sess['csrf']})
        if method=='POST' and path=='/api/login':
            data=self.read_body(); username=required(data,'username',60).lower(); password=required(data,'password',200)
            user=get_user(con,username)
            if not user or not password_ok(password,user['password_hash']):
                return self.send_json({'error':'Incorrect username or password.'},401)
            token=secrets.token_urlsafe(32); csrf=secrets.token_urlsafe(24)
            expiration=(datetime.now(timezone.utc)+timedelta(hours=8)).isoformat(timespec='seconds').replace('+00:00','Z')
            con.execute('INSERT INTO sessions (token_hash,user_id,csrf,expires_at) VALUES (?,?,?,?)',
                        (hashlib.sha256(token.encode()).hexdigest(),user['id'],csrf,expiration))
            log(con,user['id'],'LOGIN','SESSION','Demonstration session started')
            con.commit()
            secure='; Secure' if PUBLIC_DEMO else ''
            header={'Set-Cookie':f'cris_session={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age=28800{secure}'}
            return self.send_json({'authenticated':True,'csrf':csrf,'user':{k:user[k] for k in ('id','username','display_name','role')}},200,header)
        if not sess: raise ApiError(401,'Please sign in to continue.')
        if method in ('POST','PATCH','DELETE'):
            if not hmac.compare_digest(self.headers.get('X-CSRF-Token',''),sess['csrf']):
                raise ApiError(403,'Invalid request token. Please sign in again.')
        actor=sess['id']; role=sess['role']
        def restricted(*roles):
            if role not in roles:
                log(con,actor,'ACCESS_DENIED',path,f'Role: {role}')
                con.commit(); raise ApiError(403,'Your role does not permit this action.')
        if method=='POST' and path=='/api/logout':
            cookies=SimpleCookie(); cookies.load(self.headers.get('Cookie',''))
            if 'cris_session' in cookies:
                con.execute('DELETE FROM sessions WHERE token_hash=?',(hashlib.sha256(cookies['cris_session'].value.encode()).hexdigest(),))
            log(con,actor,'LOGOUT','SESSION');con.commit()
            secure='; Secure' if PUBLIC_DEMO else ''
            return self.send_json({'ok':True},200,{'Set-Cookie':f'cris_session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0{secure}'})
        if method=='GET' and path=='/api/dashboard':
            metrics={
                'cases':con.execute('SELECT COUNT(*) FROM case_files').fetchone()[0],
                'active':con.execute("SELECT COUNT(*) FROM case_files WHERE status IN ('Open','Under Investigation','Pending Review')").fetchone()[0],
                'resolved':con.execute("SELECT COUNT(*) FROM case_files WHERE status IN ('Resolved','Closed')").fetchone()[0],
                'incidents':con.execute('SELECT COUNT(*) FROM incidents').fetchone()[0],
                'evidence':con.execute('SELECT COUNT(*) FROM evidence').fetchone()[0],
            }
            recent=query_all(con,'''SELECT c.id,c.reference,c.title,c.status,c.priority,i.category,i.location,c.created_at
                FROM case_files c JOIN incidents i ON i.id=c.incident_id ORDER BY c.id DESC LIMIT 6''')
            activity=query_all(con,'''SELECT a.action,a.target,a.detail,a.created_at,coalesce(u.display_name,'System') as actor
                FROM audit_log a LEFT JOIN users u ON a.user_id=u.id ORDER BY a.id DESC LIMIT 5''')
            return self.send_json({'metrics':metrics,'recent_cases':recent,'activity':activity,**self.report_data(con)})
        if method=='GET' and path=='/api/incidents':
            q=(params.get('q',[''])[0] or '').strip()[:100]
            search=f'%{q}%'
            data=query_all(con,'''SELECT i.*,u.display_name AS reporter,
               (SELECT COUNT(*) FROM case_files c WHERE c.incident_id=i.id) AS case_count
               FROM incidents i LEFT JOIN users u ON u.id=i.created_by
               WHERE i.reference LIKE ? OR i.category LIKE ? OR i.location LIKE ? OR i.summary LIKE ?
               ORDER BY i.id DESC LIMIT 500''',(search,)*4)
            return self.send_json({'items':data})
        if method=='POST' and path=='/api/incidents':
            restricted('administrator','officer'); d=self.read_body()
            cat=enum(d,'category',CATEGORIES); occurred=date_field(d,'occurred_on'); reported=date_field(d,'reported_on')
            if reported < occurred: raise ApiError(400,'Report date cannot be before occurrence date.')
            location=required(d,'location',160); summary=required(d,'summary',1200)
            now=utcnow()
            with DATA_LOCK:
                cur=con.execute('INSERT INTO incidents(category,occurred_on,reported_on,location,summary,created_by,created_at) VALUES (?,?,?,?,?,?,?)',
                                (cat,occurred,reported,location,summary,actor,now))
                rid=cur.lastrowid; reference=ref('INC',rid)
                con.execute('UPDATE incidents SET reference=? WHERE id=?',(reference,rid)); log(con,actor,'CREATE_INCIDENT',reference,cat)
                con.commit()
            return self.send_json({'ok':True,'id':rid,'reference':reference},201)
        if method=='GET' and path=='/api/cases':
            q=(params.get('q',[''])[0] or '').strip()[:100]; status=(params.get('status',[''])[0] or '').strip(); priority=(params.get('priority',[''])[0] or '').strip()
            if status and status not in STATUSES: raise ApiError(400,'Invalid status filter.')
            if priority and priority not in PRIORITIES: raise ApiError(400,'Invalid priority filter.')
            search=f'%{q}%'
            data=query_all(con,'''SELECT c.*,i.reference AS incident_reference,i.category,i.location,i.occurred_on,
                coalesce(u.display_name,'Unassigned') AS assigned_name,
                (SELECT COUNT(*) FROM evidence e WHERE e.case_id=c.id) AS evidence_count,
                (SELECT COUNT(*) FROM involvements v WHERE v.case_id=c.id) AS people_count
                FROM case_files c JOIN incidents i ON c.incident_id=i.id LEFT JOIN users u ON c.assigned_to=u.id
                WHERE (c.reference LIKE ? OR c.title LIKE ? OR i.category LIKE ? OR i.location LIKE ?)
                AND (?='' OR c.status=?) AND (?='' OR c.priority=?)
                ORDER BY c.id DESC LIMIT 500''',(search,)*4+(status,status,priority,priority))
            return self.send_json({'items':data})
        if method=='POST' and path=='/api/cases':
            restricted('administrator','officer'); d=self.read_body()
            incident_id=valid_id(d.get('incident_id')); incident=con.execute('SELECT id FROM incidents WHERE id=?',(incident_id,)).fetchone()
            if not incident: raise ApiError(400,'Select an existing incident.')
            assignee=valid_id(d.get('assigned_to',2)); valid_assignee=con.execute("SELECT 1 FROM users WHERE id=? AND role IN ('administrator','officer') AND active=1",(assignee,)).fetchone()
            if not valid_assignee: raise ApiError(400,'Assign an active officer or administrator.')
            title=required(d,'title',140); details=optional(d,'details',3000); priority=enum(d,'priority',PRIORITIES,'Medium'); now=utcnow()
            with DATA_LOCK:
                cur=con.execute('INSERT INTO case_files(incident_id,title,details,priority,status,assigned_to,created_by,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)',
                     (incident_id,title,details,priority,'Open',assignee,actor,now,now))
                rid=cur.lastrowid; reference=ref('CASE',rid)
                con.execute('UPDATE case_files SET reference=? WHERE id=?',(reference,rid))
                con.execute('INSERT INTO status_history (case_id,old_status,new_status,reason,changed_by,created_at) VALUES (?,?,?,?,?,?)',
                            (rid,None,'Open','Case registration',actor,now))
                log(con,actor,'CREATE_CASE',reference,title);con.commit()
            return self.send_json({'ok':True,'id':rid,'reference':reference},201)
        if path.startswith('/api/cases/') and path.count('/')==3:
            case_id=valid_id(path.rsplit('/',1)[1]); rec=con.execute('SELECT * FROM case_files WHERE id=?',(case_id,)).fetchone()
            if not rec: raise ApiError(404,'Case not found.')
            if method=='GET':
                participants=[]; proofs=[]
                if role!='analyst':
                    participants=query_all(con,'''SELECT v.id,p.reference,p.full_name,v.role FROM involvements v
                        JOIN people p ON p.id=v.person_id WHERE v.case_id=? ORDER BY v.id DESC''',(case_id,))
                    proofs=query_all(con,'SELECT * FROM evidence WHERE case_id=? ORDER BY id DESC',(case_id,))
                history=query_all(con,'''SELECT h.*,u.display_name AS actor FROM status_history h
                    LEFT JOIN users u ON u.id=h.changed_by WHERE h.case_id=? ORDER BY h.id DESC''',(case_id,))
                return self.send_json({'case':dict(rec),'participants':participants,'evidence':proofs,'history':history})
            if method=='PATCH':
                restricted('administrator','officer'); d=self.read_body()
                title=required(d,'title',140); details=optional(d,'details',3000)
                priority=enum(d,'priority',PRIORITIES); status=enum(d,'status',STATUSES)
                assigned=valid_id(d.get('assigned_to',rec['assigned_to']))
                if not con.execute("SELECT 1 FROM users WHERE id=? AND role IN ('administrator','officer') AND active=1",(assigned,)).fetchone():
                    raise ApiError(400,'Invalid assigned officer.')
                reason=optional(d,'reason',400)
                if status!=rec['status'] and not reason: raise ApiError(400,'A reason is required when changing case status.')
                now=utcnow()
                con.execute('UPDATE case_files SET title=?,details=?,priority=?,status=?,assigned_to=?,updated_at=? WHERE id=?',
                            (title,details,priority,status,assigned,now,case_id))
                if status!=rec['status']:
                    con.execute('INSERT INTO status_history (case_id,old_status,new_status,reason,changed_by,created_at) VALUES (?,?,?,?,?,?)',
                               (case_id,rec['status'],status,reason,actor,now))
                log(con,actor,'UPDATE_CASE',rec['reference'],f'Status: {rec["status"]} → {status}. {reason}')
                con.commit()
                return self.send_json({'ok':True,'reference':rec['reference']})
        if method=='GET' and path=='/api/people':
            restricted('administrator','officer'); q=f'%{(params.get("q",[""])[0] or "").strip()[:100]}%'
            data=query_all(con,'''SELECT p.*,(SELECT COUNT(*) FROM involvements v WHERE v.person_id=p.id) AS links
                FROM people p WHERE p.full_name LIKE ? OR p.reference LIKE ? ORDER BY p.id DESC LIMIT 500''',(q,q))
            return self.send_json({'items':data})
        if method=='POST' and path=='/api/people':
            restricted('administrator','officer');d=self.read_body()
            name=required(d,'full_name',130); description=optional(d,'description',500)
            with DATA_LOCK:
                cur=con.execute('INSERT INTO people(full_name,description,created_by,created_at) VALUES (?,?,?,?)',(name,description,actor,utcnow()))
                rid=cur.lastrowid; reference=ref('PER',rid)
                con.execute('UPDATE people SET reference=? WHERE id=?',(reference,rid))
                log(con,actor,'CREATE_PERSON',reference,'Role-neutral person record');con.commit()
            return self.send_json({'ok':True,'id':rid,'reference':reference},201)
        if method=='POST' and path=='/api/involvements':
            restricted('administrator','officer');d=self.read_body()
            cid=valid_id(d.get('case_id')); pid=valid_id(d.get('person_id')); role_name=enum(d,'role',INVOLVEMENT_ROLES)
            if not con.execute('SELECT 1 FROM case_files WHERE id=?',(cid,)).fetchone(): raise ApiError(400,'Case not found.')
            if not con.execute('SELECT 1 FROM people WHERE id=?',(pid,)).fetchone(): raise ApiError(400,'Person not found.')
            con.execute('INSERT INTO involvements(case_id,person_id,role) VALUES (?,?,?)',(cid,pid,role_name))
            log(con,actor,'LINK_PERSON',f'CASE-{cid}',role_name);con.commit()
            return self.send_json({'ok':True},201)
        if method=='GET' and path=='/api/evidence':
            restricted('administrator','officer')
            q=f'%{(params.get("q",[""])[0] or "").strip()[:100]}%'
            return self.send_json({'items':query_all(con,'''SELECT e.*,c.reference AS case_reference,c.title AS case_title
                FROM evidence e JOIN case_files c ON e.case_id=c.id
                WHERE e.reference LIKE ? OR e.item_name LIKE ? OR c.reference LIKE ?
                ORDER BY e.id DESC LIMIT 500''',(q,q,q))})
        if method=='POST' and path=='/api/evidence':
            restricted('administrator','officer'); d=self.read_body()
            case_id=valid_id(d.get('case_id'))
            if not con.execute('SELECT 1 FROM case_files WHERE id=?',(case_id,)).fetchone(): raise ApiError(400,'Select an existing case.')
            name=required(d,'item_name',140);description=optional(d,'description',1000); day=date_field(d,'collected_on')
            storage=required(d,'storage_location',150); custodian=required(d,'custodian',130)
            with DATA_LOCK:
                cur=con.execute('INSERT INTO evidence(case_id,item_name,description,collected_on,storage_location,custodian,created_by,created_at) VALUES (?,?,?,?,?,?,?,?)',
                         (case_id,name,description,day,storage,custodian,actor,utcnow()))
                rid=cur.lastrowid; reference=ref('EVD',rid)
                con.execute('UPDATE evidence SET reference=? WHERE id=?',(reference,rid))
                log(con,actor,'CREATE_EVIDENCE',reference,name);con.commit()
            return self.send_json({'ok':True,'reference':reference},201)
        if method=='GET' and path=='/api/reports': return self.send_json(self.report_data(con))
        if method=='GET' and path=='/api/users':
            restricted('administrator','officer')
            return self.send_json({'items':query_all(con,'SELECT id,username,display_name,role,active FROM users ORDER BY id')})
        if method=='GET' and path=='/api/audit':
            restricted('administrator')
            data=query_all(con,'''SELECT a.*,coalesce(u.display_name,'System') AS actor FROM audit_log a
                LEFT JOIN users u ON u.id=a.user_id ORDER BY a.id DESC LIMIT 150''')
            return self.send_json({'items':data})
        if method=='GET' and path=='/api/export/cases':
            restricted('administrator','analyst')
            cases=query_all(con,'''SELECT c.reference,c.title,c.priority,c.status,i.category,i.location,
                i.occurred_on,c.created_at FROM case_files c JOIN incidents i ON i.id=c.incident_id
                ORDER BY c.id DESC''')
            fields=['reference','title','priority','status','category','location','occurred_on','created_at']
            output=io.StringIO(); writer=csv.DictWriter(output,fieldnames=fields);writer.writeheader()
            for item in cases:
                # Prevent spreadsheet formula injection in user-provided fields.
                safe={k:("'"+str(item[k]) if str(item[k]).lstrip().startswith(('=','+','-','@')) else item[k]) for k in fields}
                writer.writerow(safe)
            raw=output.getvalue().encode('utf-8-sig')
            log(con,actor,'EXPORT_CASE_SUMMARY','CSV','No person-level data included');con.commit()
            self.send_response(200);self.send_header('Content-Type','text/csv; charset=utf-8')
            self.send_header('Content-Disposition','attachment; filename="cris-case-summary.csv"')
            self.send_header('X-Content-Type-Options','nosniff');self.send_header('Content-Length',str(len(raw)))
            self.end_headers();self.wfile.write(raw);return
        raise ApiError(404,'Endpoint not found.')
    def report_data(self,con):
        by_status=query_all(con,'SELECT status AS name,COUNT(*) AS count FROM case_files GROUP BY status ORDER BY count DESC')
        by_category=query_all(con,'''SELECT i.category AS name, COUNT(*) AS count FROM case_files c
            JOIN incidents i ON i.id=c.incident_id GROUP BY i.category ORDER BY count DESC''')
        monthly=query_all(con,'''SELECT substr(created_at,1,7) AS month,COUNT(*) AS count FROM case_files
            GROUP BY substr(created_at,1,7) ORDER BY month''')
        by_location=query_all(con,'''SELECT i.location AS name,COUNT(*) AS count FROM case_files c
            JOIN incidents i ON c.incident_id=i.id GROUP BY i.location ORDER BY count DESC LIMIT 8''')
        total=con.execute('SELECT COUNT(*) FROM case_files').fetchone()[0]
        resolved=con.execute("SELECT COUNT(*) FROM case_files WHERE status IN ('Closed','Resolved')").fetchone()[0]
        return {'total':total,'resolved':resolved,'by_status':by_status,'by_category':by_category,
                'monthly':monthly,'by_location':by_location,'data_note':'Fictional demonstration records. Counts describe records entered, not crime prevalence.'}

def serve(host=HOST, port=PORT):
    init_db()
    server=ThreadingHTTPServer((host,port),Handler)
    print(f'\n  {PROJECT}\n  Open http://{host}:{server.server_port}\n  Academic demo • fictional data only • press Ctrl+C to stop\n')
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally:server.server_close()

if __name__=='__main__': serve()
