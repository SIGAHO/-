"""Explicit Web bridge for one workspace agent job at a time; no test execution."""
import json
import threading
import urllib.parse

from breaktail_agent import Workspace
from breaktail_agent_queue import AgentQueue
from breaktail_orchestrator import load_config


class WebAgentService:
    def __init__(self, config_loader=load_config, model=None):
        self.config_loader = config_loader
        self.model = model
        self.lock = threading.Lock()
        self.workers = {}
        self.worker_errors = {}

    def _root(self, root):
        return str(Workspace(root, create_audit=False).root)

    def _config(self):
        config = self.config_loader()
        if config.get("safe_mode"):
            raise ValueError("安全モードでは作業エージェントを実行できません")
        if urllib.parse.urlparse(config.get("ollama_url", "")).hostname not in ("127.0.0.1", "localhost"):
            raise ValueError("Web作業エージェントはローカルのOllamaだけ利用できます")
        return config

    def _start_worker(self, root, config):
        thread = self.workers.get(root)
        if thread is not None and thread.is_alive():
            raise ValueError("この作業フォルダーでは別の作業を処理中です")
        self.worker_errors.pop(root, None)
        thread = threading.Thread(target=self._work, args=(root, config), daemon=True,
                                  name="breaktail-agent-web")
        self.workers[root] = thread
        thread.start()

    def _work(self, root, config):
        try:
            with AgentQueue(root) as queue:
                queue.work_one(config, allow_execution=False, max_steps=8,
                               max_seconds=240, model=self.model)
        except Exception as error:
            with self.lock:
                self.worker_errors[root] = type(error).__name__ + ": " + str(error)[:300]

    def start(self, root, task):
        root = self._root(root)
        if not isinstance(task, str) or not task.strip() or len(task) > 2000:
            raise ValueError("依頼を2000文字以内で指定してください")
        config = self._config()
        with self.lock:
            if (self.workers.get(root) is not None and self.workers[root].is_alive()):
                raise ValueError("この作業フォルダーでは別の作業を処理中です")
            with AgentQueue(root) as queue:
                if queue.db.execute("SELECT 1 FROM jobs WHERE status='queued' LIMIT 1").fetchone():
                    raise ValueError("待機中の作業を先に確認してください")
                job = queue.enqueue(task, model=config["model"])
            self._start_worker(root, config)
        return {"workspace": root, "job_id": job["id"], "status": job["status"],
                "execution_enabled": False}

    def resume(self, root, run_id):
        root = self._root(root)
        config = self._config()
        with self.lock:
            if (self.workers.get(root) is not None and self.workers[root].is_alive()):
                raise ValueError("この作業フォルダーでは別の作業を処理中です")
            with AgentQueue(root) as queue:
                if queue.db.execute("SELECT 1 FROM jobs WHERE status='queued' LIMIT 1").fetchone():
                    raise ValueError("待機中の作業を先に確認してください")
                job = queue.enqueue_resume(run_id, model=config["model"])
            self._start_worker(root, config)
        return {"workspace": root, "job_id": job["id"], "status": job["status"],
                "resumed_from": run_id, "execution_enabled": False}

    def work_queued(self, root, job_id):
        root = self._root(root)
        config = self._config()
        with self.lock:
            with AgentQueue(root) as queue:
                if queue.get(job_id)["status"] != "queued":
                    raise ValueError("待機中の作業だけ再試行できます")
                oldest = queue.db.execute("SELECT id FROM jobs WHERE status='queued' ORDER BY seq LIMIT 1").fetchone()
                if oldest[0] != job_id:
                    raise ValueError("先に投入された作業を確認してください")
            self._start_worker(root, config)
        return {"workspace": root, "job_id": job_id, "status": "queued"}

    def cancel(self, root, job_id):
        root = self._root(root)
        with AgentQueue(root) as queue:
            job = queue.cancel(job_id)
        return {"workspace": root, "job_id": job["id"], "status": job["status"],
                "cancel_requested": bool(job["cancel_requested"])}

    def status(self, root, job_id):
        root = self._root(root)
        with AgentQueue(root) as queue:
            job = queue.get(job_id)
        result = job["result"] or {}
        events = []
        if job["run_id"]:
            workspace = Workspace(root, create_audit=False)
            event_file = workspace.path(".breaktail-agent/" + job["run_id"] + "/events.jsonl", internal=True)
            if event_file.is_file():
                with event_file.open("rb") as stream:
                    stream.seek(max(0, event_file.stat().st_size - 32000))
                    lines = stream.read().decode("utf-8", errors="replace").splitlines()
                for line in lines[-12:]:
                    try:
                        event = json.loads(line)
                        item = {key: event[key] for key in ("step", "tool", "error", "detail")
                                if key in event}
                        if isinstance(event.get("args"), dict):
                            item["path"] = event["args"].get("path")
                        if "result" in event:
                            item["observation"] = event["result"]
                        elif "observation" in event:
                            item["observation"] = event["observation"]
                        events.append(item)
                    except (ValueError, TypeError):
                        continue
        with self.lock:
            worker_error = self.worker_errors.get(root) if job["status"] == "queued" else None
        return {"workspace": root, "job_id": job["id"], "status": job["status"],
                "run_id": job["run_id"], "cancel_requested": bool(job["cancel_requested"]),
                "error": job["error"] or worker_error, "summary": result.get("summary"),
                "changes": result.get("changes", []), "syntax_verified": result.get("syntax_verified"),
                "tests_passed": result.get("tests_passed"), "execution_enabled": result.get("execution_enabled", False),
                "acceptance": result.get("acceptance"), "events": events}

