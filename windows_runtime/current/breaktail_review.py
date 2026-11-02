"""Breaktail human review. Standard library only; never writes source artifacts."""
import argparse
import hashlib
import json
import os
import secrets
import socket
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from breaktail_paths import store_path

HERE = Path(__file__).resolve().parent
DEFAULT_DB = store_path('review', 'reviews.sqlite3', 'BREAKTAIL_REVIEW_DB')

def packed(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))

def digest(value):
    return hashlib.sha256(packed(value).encode('utf-8')).hexdigest()

def now():
    return datetime.now(timezone.utc).isoformat()

class Conflict(ValueError):
    pass

class Store:
    def __init__(self, path=DEFAULT_DB):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS results (
              seq INTEGER PRIMARY KEY AUTOINCREMENT, review_id TEXT UNIQUE NOT NULL,
              identity TEXT UNIQUE NOT NULL, content_hash TEXT NOT NULL,
              source_type TEXT NOT NULL, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS sources (
              review_id TEXT NOT NULL, source_file TEXT NOT NULL, source_index TEXT NOT NULL,
              source_ref TEXT NOT NULL, metadata TEXT NOT NULL,
              UNIQUE(review_id,source_file,source_index));
            CREATE TABLE IF NOT EXISTS reviews (
              review_id TEXT PRIMARY KEY, decision TEXT NOT NULL DEFAULT 'pending'
              CHECK(decision IN ('pending','approved','rejected')),
              note TEXT NOT NULL DEFAULT '', reviewed_at TEXT, version INTEGER NOT NULL DEFAULT 0,
              reason_codes TEXT NOT NULL DEFAULT '[]');
            CREATE TABLE IF NOT EXISTS review_history (
              id INTEGER PRIMARY KEY AUTOINCREMENT, review_id TEXT NOT NULL,
              decision TEXT NOT NULL, note TEXT NOT NULL, reviewed_at TEXT NOT NULL, version INTEGER NOT NULL,
              reason_codes TEXT NOT NULL DEFAULT '[]');
            ''')
            # Non-destructive migration for databases created by the original UI.
            for table in ('reviews', 'review_history'):
                columns = {row['name'] for row in db.execute(f'PRAGMA table_info({table})')}
                if 'reason_codes' not in columns:
                    db.execute(f"ALTER TABLE {table} ADD COLUMN reason_codes TEXT NOT NULL DEFAULT '[]'")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=20)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def add(self, records):
        """Atomic append. Caller supplies stable identity and immutable result content."""
        added = 0
        with self.connect() as db:
            for record in records:
                identity = record['identity']
                content = record['content']
                source_type = record['source_type']
                if not isinstance(identity, str) or not identity or not isinstance(content, dict):
                    raise ValueError('identity/content が不正です')
                h = digest(content)
                rid = 'review_' + digest(identity)
                old = db.execute('SELECT content_hash FROM results WHERE identity=?', (identity,)).fetchone()
                if old and old[0] != h:
                    raise Conflict('同じ結果IDの内容が変わっています。新しいrun_id/result_idを使用してください: ' + identity)
                if not old:
                    db.execute('INSERT INTO results(review_id,identity,content_hash,source_type,payload) VALUES (?,?,?,?,?)',
                               (rid, identity, h, source_type, packed(content)))
                    db.execute('INSERT INTO reviews(review_id) VALUES (?)', (rid,))
                    added += 1
                for source in record.get('sources', []):
                    db.execute('INSERT OR IGNORE INTO sources VALUES (?,?,?,?,?)',
                        (rid, str(source.get('source_file','')), str(source.get('source_index','')),
                         str(source.get('source_ref','')), packed(source.get('metadata', {}))))
        return added

    def listing(self, decision='pending', source_type='', search=''):
        if decision not in ('pending','approved','rejected','all'):
            raise ValueError('絞り込みが不正です')
        with self.connect() as db:
            counts = {'pending':0,'approved':0,'rejected':0}
            counts.update(dict(db.execute('SELECT decision,count(*) FROM reviews GROUP BY decision')))
            where, args = [], []
            if decision != 'all': where.append('v.decision=?'); args.append(decision)
            if source_type: where.append('r.source_type=?'); args.append(source_type)
            if search: where.append('(r.payload LIKE ? OR r.identity LIKE ?)'); args.extend(['%'+search+'%']*2)
            sql = 'SELECT r.seq,r.review_id,r.identity,r.source_type,v.decision FROM results r JOIN reviews v USING(review_id)'
            if where: sql += ' WHERE ' + ' AND '.join(where)
            rows = [dict(x) for x in db.execute(sql+' ORDER BY r.seq',args)]
            types = dict(db.execute('SELECT source_type,count(*) FROM results GROUP BY source_type'))
        return {'counts':counts,'items':rows,'types':types,'total':sum(counts.values())}

    def get(self, rid):
        with self.connect() as db:
            row = db.execute('SELECT r.*,v.decision,v.note,v.reviewed_at,v.version,v.reason_codes FROM results r JOIN reviews v USING(review_id) WHERE review_id=?',(rid,)).fetchone()
            if not row: raise KeyError(rid)
            result = dict(row); result['content'] = json.loads(result.pop('payload'))
            result['reason_codes'] = json.loads(result['reason_codes'])
            result['sources'] = [dict(x) for x in db.execute('SELECT * FROM sources WHERE review_id=?',(rid,))]
            for s in result['sources']: s['metadata'] = json.loads(s['metadata'])
            result['history'] = [dict(x) for x in db.execute('SELECT * FROM review_history WHERE review_id=? ORDER BY id DESC',(rid,))]
            for entry in result['history']:
                entry['reason_codes'] = json.loads(entry['reason_codes'])
            result['progress'] = dict(db.execute('''
                SELECT
                  (SELECT count(*) FROM results x WHERE x.source_type=r.source_type AND x.seq<=r.seq) AS position,
                  (SELECT count(*) FROM results x WHERE x.source_type=r.source_type) AS total,
                  (SELECT count(*) FROM results x JOIN reviews y USING(review_id)
                    WHERE x.source_type=r.source_type AND y.decision='pending') AS pending
                FROM results r WHERE r.review_id=?
            ''',(rid,)).fetchone())
            return result

    def decide(self, rid, decision, note, version, reason_codes=None):
        reason_codes = [] if reason_codes is None else reason_codes
        allowed_reasons = {'agree_too_early','overconfident','unnatural','question_back','invented_subject','too_thin','other'}
        if (decision not in ('approved','rejected','pending') or not isinstance(note,str) or len(note)>100000
                or type(version) is not int or not isinstance(reason_codes,list)
                or any(not isinstance(x,str) or x not in allowed_reasons for x in reason_codes)
                or len(reason_codes) != len(set(reason_codes))):
            raise ValueError('判定・所見・version が不正です')
        if decision != 'rejected':
            reason_codes = []
        reasons = packed(reason_codes)
        stamp = now()
        with self.connect() as db:
            cur = db.execute('UPDATE reviews SET decision=?,note=?,reviewed_at=?,version=version+1,reason_codes=? WHERE review_id=? AND version=?',
                             (decision,note,stamp,reasons,rid,version))
            if cur.rowcount != 1: raise Conflict('別画面で更新済みです。再読み込みして確認してください。')
            db.execute('INSERT INTO review_history(review_id,decision,note,reviewed_at,version,reason_codes) VALUES (?,?,?,?,?,?)',
                       (rid,decision,note,stamp,version+1,reasons))
        return self.get(rid)

def import_future(store, path):
    """JSONL contract for Base/QLoRA and future evaluations; all lines validated first."""
    path = Path(path).resolve()
    records = []
    for line, text in enumerate(path.read_text(encoding='utf-8-sig').splitlines(),1):
        if not text.strip(): continue
        r = json.loads(text)
        for key in ('run_id','case_id','variant','model','output'):
            if not isinstance(r.get(key),str) or not r[key]: raise ValueError(f'{line}: {key} が必要です')
        if 'input' not in r and 'messages' not in r: raise ValueError(f'{line}: input または messages が必要です')
        identity = 'future:' + packed([r['run_id'],r['case_id'],r['variant'],r.get('trial',0)])
        records.append({'identity':identity,'source_type':r.get('source_type','future_model_eval'),
          'content':r,'sources':[{'source_file':str(path),'source_index':line,'source_ref':r.get('source_ref','')}]})
    return store.add(records)

class ReviewApp:
    def __init__(self, db=DEFAULT_DB, demo=False):
        self.store = Store(db)
        self.token = secrets.token_urlsafe(32)
        self.demo = demo

    def handle(self, h):
        url = urlparse(h.path)
        if not (url.path == '/review' or url.path.startswith('/review/')): return False
        def send(code, obj, html=False):
            body = obj.encode('utf-8') if html else packed(obj).encode('utf-8')
            h.send_response(code)
            h.send_header('Content-Type','text/html; charset=utf-8' if html else 'application/json; charset=utf-8')
            h.send_header('Content-Length',str(len(body)))
            h.send_header('Cache-Control','no-store')
            h.send_header('X-Content-Type-Options','nosniff')
            h.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'")
            h.end_headers(); h.wfile.write(body)
        try:
            host = h.headers.get('Host','')
            if host.split(':')[0] not in ('127.0.0.1','localhost'):
                send(403,{'error':'ローカルURLを使用してください'}); return True
            if h.command == 'GET':
                q = {k:v[0] for k,v in parse_qs(url.query).items()}
                if url.path in ('/review','/review/'):
                    page = HERE.joinpath('breaktail_review.html').read_text(encoding='utf-8')
                    send(200,page.replace('__TOKEN__',self.token).replace('__MODE__','動作確認用 — 本人の判定には保存しません' if self.demo else '本人レビュー — 判定は専用DBへ保存'),True)
                elif url.path == '/review/api/list': send(200,self.store.listing(q.get('decision','pending'),q.get('type',''),q.get('search','')))
                elif url.path == '/review/api/item': send(200,self.store.get(q['id']))
                else: send(404,{'error':'見つかりません'})
            elif h.command == 'POST':
                if h.headers.get('X-Review-Token') != self.token:
                    send(403,{'error':'この画面から操作してください'}); return True
                origin = h.headers.get('Origin')
                if origin and origin != 'http://'+host:
                    send(403,{'error':'Originが一致しません'}); return True
                size = int(h.headers.get('Content-Length','0'))
                if not 0<size<=500000: raise ValueError('入力サイズが不正です')
                r = json.loads(h.rfile.read(size))
                if url.path != '/review/api/decision': send(404,{'error':'見つかりません'})
                else: send(200,self.store.decide(r['review_id'],r['decision'],r.get('note',''),r['version'],r.get('reason_codes',[])))
            else: send(405,{'error':'Method not allowed'})
        except Conflict as e: send(409,{'error':str(e)})
        except KeyError as e: send(404,{'error':'対象がありません: '+str(e)})
        except (ValueError,TypeError) as e: send(400,{'error':str(e)})
        except Exception:
            import traceback
            traceback.print_exc()
            send(500,{'error':'保存に失敗しました。画面の所見を保持したまま再試行してください。'})
        return True

def serve(db, port, demo=False):
    app = ReviewApp(db,demo)
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == '/':
                self.send_response(302); self.send_header('Location','/review'); self.end_headers(); return
            if not app.handle(self): self.send_error(404)
        def do_POST(self):
            if not app.handle(self): self.send_error(404)
    class Server(ThreadingHTTPServer):
        allow_reuse_address = False
        def server_bind(self):
            if os.name == 'nt': self.socket.setsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE,1)
            super().server_bind()
    with Server(('127.0.0.1',port),Handler) as server:
        print(f'http://127.0.0.1:{port}/review',flush=True)
        server.serve_forever()

if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--db',type=Path,default=DEFAULT_DB)
    parser.add_argument('--port',type=int,default=8770)
    parser.add_argument('--import-jsonl',type=Path)
    parser.add_argument('--demo',action='store_true')
    a=parser.parse_args()
    if a.import_jsonl: print('added:',import_future(Store(a.db),a.import_jsonl))
    else: serve(a.db,a.port,a.demo)
