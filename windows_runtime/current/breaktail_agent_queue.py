"""Workspace-local durable queue. One explicit worker invocation runs one job."""
import json
import os
import re
import sqlite3
import time
import uuid

from breaktail_agent import Workspace,run_agent,request_cancel
from breaktail_agent_requirements import normalize
from breaktail_file_lock import ExclusiveLock
from breaktail_agent_control import RunControl
from breaktail_agent_resume import load as load_resume
from breaktail_agent_preferences import validate_conversation_id


class AgentQueue:
    def __init__(self,root):
        self.workspace=Workspace(root,create_audit=False)
        self.root=self.workspace.root
        self.path=self.workspace.path('.breaktail-agent/queue.sqlite3',internal=True)
        for suffix in ('-wal','-shm','-journal'):
            self.workspace.path('.breaktail-agent/queue.sqlite3'+suffix,internal=True)
        self.path.parent.mkdir(parents=True,exist_ok=True)
        self.db=sqlite3.connect(self.path,timeout=10)
        self.db.row_factory=sqlite3.Row
        self.db.execute('PRAGMA trusted_schema=OFF')
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=FULL')
        if self.db.execute('PRAGMA user_version').fetchone()[0] not in (0,1):
            self.db.close()
            raise ValueError('unsupported agent queue version')
        self.db.executescript('''CREATE TABLE IF NOT EXISTS jobs(
            seq INTEGER PRIMARY KEY AUTOINCREMENT,id TEXT NOT NULL UNIQUE,
            payload TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'queued',
            run_id TEXT,result TEXT,error TEXT,cancel_requested INTEGER NOT NULL DEFAULT 0,
            created_at REAL NOT NULL,worker_pid INTEGER);
            PRAGMA user_version=1;''')

    def __enter__(self):return self
    def __exit__(self,*args):self.db.close()

    def get(self,identity):
        row=self.db.execute('SELECT * FROM jobs WHERE id=?',(identity,)).fetchone()
        if row is None:raise ValueError('unknown queue task id')
        value=dict(row)
        value['payload']=json.loads(value['payload'])
        value['result']=json.loads(value['result']) if value['result'] else None
        return value

    def list(self,limit=100):
        if type(limit) is not int or not 1<=limit<=1000:raise ValueError('queue limit must be 1..1000')
        return [dict(row) for row in self.db.execute(
            'SELECT id,status,run_id,cancel_requested,error FROM jobs ORDER BY seq DESC LIMIT ?',(limit,))]

    def enqueue(self,task,requirements=None,*,identity=None,model=None,conversation_id=None,resume_run_id=None):
        if not isinstance(task,str) or not task.strip() or len(task)>16000:raise ValueError('task must be 1..16000 characters')
        if resume_run_id is not None and (requirements is not None or conversation_id is not None):
            raise ValueError('resumed task keeps its original requirements and conversation scope')
        identity=identity or uuid.uuid4().hex
        if not isinstance(identity,str) or not re.fullmatch(r'[0-9a-f]{32}',identity):raise ValueError('queue task id must be 32 lowercase hexadecimal characters')
        requirements=normalize(self.workspace,requirements)
        payload_value={'task':task,'requirements':requirements,'model':model}
        if resume_run_id is not None:payload_value['resume_run_id']=resume_run_id
        if conversation_id is not None:payload_value['conversation_id']=validate_conversation_id(conversation_id)
        payload=json.dumps(payload_value,ensure_ascii=False,sort_keys=True,allow_nan=False)
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO jobs(id,payload,created_at) VALUES (?,?,?)',(identity,payload,time.time()))
            saved=self.db.execute('SELECT payload FROM jobs WHERE id=?',(identity,)).fetchone()[0]
            if saved!=payload:raise ValueError('queue task id belongs to a different request')
        return self.get(identity)

    def enqueue_resume(self,run_id,*,identity=None,model=None):
        checkpoint=load_resume(self.workspace,run_id,model)
        return self.enqueue(checkpoint['task'],identity=identity,model=model,resume_run_id=run_id)

    def cancel(self,identity):
        try:
            self.db.execute('BEGIN IMMEDIATE')
            row=self.get(identity)
            if row['status']=='queued':
                self.db.execute("UPDATE jobs SET status='cancelled',cancel_requested=1 WHERE id=?",(identity,))
                self.db.commit()
                return self.get(identity)
            if row['status']!='running':
                self.db.commit()
                return row
            self.db.execute('UPDATE jobs SET cancel_requested=1 WHERE id=?',(identity,))
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        row=self.get(identity)
        if row['run_id'] is not None:request_cancel(self.workspace,row['run_id'])
        return row

    def work_one(self,config,*,allow_execution=False,max_steps=16,max_seconds=900,model=None):
        if type(max_steps) is not int or not 1<=max_steps<=40:raise ValueError('max_steps must be 1..40')
        RunControl(self.workspace,time.monotonic(),max_seconds)
        lock=self.workspace.path('.breaktail-agent/queue.worker.lock',internal=True)
        with ExclusiveLock(lock,timeout=0):
            # A released OS lock does not prove an old running task succeeded.
            # Quarantine uncertain work instead of automatically replaying it.
            with self.db:
                self.db.execute("UPDATE jobs SET status='interrupted',error='previous worker ended without a recorded result' WHERE status='running'")
            try:
                self.db.execute('BEGIN IMMEDIATE')
                row=self.db.execute("SELECT id FROM jobs WHERE status='queued' ORDER BY seq LIMIT 1").fetchone()
                if row is None:
                    self.db.commit()
                    return None
                identity=row['id']
                self.db.execute("UPDATE jobs SET status='running',worker_pid=? WHERE id=?",(os.getpid(),identity))
                self.db.commit()
            except Exception:
                self.db.rollback()
                raise
            job=self.get(identity)
            def started(run_id):
                with self.db:self.db.execute('UPDATE jobs SET run_id=? WHERE id=?',(run_id,identity))
                if self.get(identity)['cancel_requested']:
                    request_cancel(self.workspace,run_id)
            try:
                if job['payload']['model']!=config.get('model'):raise ValueError('queued model differs from worker model')
                resume_run_id=job['payload'].get('resume_run_id')
                result=run_agent(config,self.root,None if resume_run_id else job['payload']['task'],
                    requirements=None if resume_run_id else job['payload']['requirements'],resume_run_id=resume_run_id,
                    allow_execution=allow_execution,max_steps=max_steps,max_seconds=max_seconds,model=model,on_started=started,
                    conversation_id=job['payload'].get('conversation_id'))
                with self.db:self.db.execute('UPDATE jobs SET status=?,result=? WHERE id=?',
                    (result['status'],json.dumps(result,ensure_ascii=False),identity))
            except Exception as error:
                with self.db:self.db.execute("UPDATE jobs SET status='failed',error=? WHERE id=?",(type(error).__name__+': '+str(error)[:500],identity))
            return self.get(identity)

