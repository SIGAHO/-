"""Explicit Web bridge for one workspace agent job at a time; no test execution."""
import json
import hashlib
import os
import re
import secrets
import threading
import time
import urllib.parse

from breaktail_agent import Workspace
from breaktail_agent_queue import AgentQueue
from breaktail_agent_diff import review as review_changes
from breaktail_file_lock import ExclusiveLock
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
        config = dict(self.config_loader())
        if config.get("safe_mode"):
            raise ValueError("安全モードでは作業エージェントを実行できません")
        if urllib.parse.urlparse(config.get("ollama_url", "")).hostname not in ("127.0.0.1", "localhost"):
            raise ValueError("Web作業エージェントはローカルのOllamaだけ利用できます")
        config["num_ctx"] = min(config.get("num_ctx", 8192), 4096)
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

    def _undo_recorded(self, workspace, job_id, run_id):
        if not isinstance(run_id, str) or not re.fullmatch(r"[0-9a-f]{32}", run_id):
            return False
        receipt = workspace.path(f".breaktail-agent/{run_id}/web-undo.json", internal=True)
        if not receipt.is_file() or receipt.stat().st_size > 4096:
            return False
        try:
            record = json.loads(receipt.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False
        return isinstance(record, dict) and record.get("schema") == 1 and record.get("job_id") == job_id and record.get("run_id") == run_id

    def review(self, root, job_id):
        root = self._root(root)
        with AgentQueue(root) as queue:
            job = queue.get(job_id)
        if job["status"] in ("queued", "running"):
            raise ValueError("作業終了後に差分を確認してください")
        if not isinstance(job["run_id"], str) or not re.fullmatch(r"[0-9a-f]{32}", job["run_id"]):
            raise ValueError("実行記録がありません")
        changes = (job["result"] or {}).get("changes")
        if not isinstance(changes, list):
            raise ValueError("変更記録がありません")
        workspace = Workspace(root, create_audit=False)
        for change in changes:
            if (not isinstance(change, dict) or not isinstance(change.get("path"), str) or
                    not all(isinstance(change.get(key), str) and re.fullmatch(r"[0-9a-f]{64}", change[key])
                            for key in ("after_sha256",))):
                raise ValueError("変更記録が不正です")
            target = workspace.path(change["path"])
            if str(target) in workspace.changes:
                raise ValueError("変更記録が重複しています")
            workspace.changes[str(target)] = change
        report = review_changes(workspace)
        return {"workspace": root, "job_id": job_id, "run_id": job["run_id"],
                "undone": self._undo_recorded(workspace, job_id, job["run_id"]), **report}

    def undo(self, root, job_id, expected_after_sha256):
        root = self._root(root)
        if not isinstance(expected_after_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_after_sha256):
            raise ValueError("確認した変更後ハッシュを指定してください")
        workspace = Workspace(root, create_audit=False)
        with ExclusiveLock(workspace.path(".breaktail-agent/worker.lock", internal=True)):
            report = self.review(root, job_id)
            if report["total_tracked"] != 1 or report["files_omitted"] or len(report["changes"]) != 1:
                raise ValueError("一件の既存ファイル変更だけ取り消せます")
            change = report["changes"][0]
            if (change["status"] != "modified" or change.get("integrity") != "verified" or
                    change.get("current_sha256") != expected_after_sha256 or
                    not isinstance(change.get("before_sha256"), str) or
                    not re.fullmatch(r"[0-9a-f]{64}", change["before_sha256"])):
                raise ValueError("変更内容が確認時と異なります。上書きしません")
            with AgentQueue(root) as queue:
                original = queue.get(job_id)["result"]["changes"][0]
            target = workspace.path(change["path"])
            backup = workspace.path(original["backup"], internal=True)
            receipt = workspace.path(f".breaktail-agent/{report['run_id']}/web-undo.json", internal=True)
            if receipt.exists():
                raise ValueError("この変更は既に取り消されています")
            before = backup.read_bytes()
            if (len(before) > 64000 or hashlib.sha256(before).hexdigest() != change["before_sha256"] or
                    hashlib.sha256(target.read_bytes()).hexdigest() != expected_after_sha256):
                raise ValueError("ファイルまたはバックアップが変わりました。上書きしません")
            temporary = target.with_name(target.name + "." + secrets.token_hex(8) + ".undo.tmp")
            try:
                with temporary.open("xb") as stream:
                    stream.write(before)
                    stream.flush()
                    os.fsync(stream.fileno())
                if hashlib.sha256(target.read_bytes()).hexdigest() != expected_after_sha256:
                    raise ValueError("保存後にファイルが変わりました。上書きしません")
                os.replace(temporary, target)
            finally:
                temporary.unlink(missing_ok=True)
            if hashlib.sha256(target.read_bytes()).hexdigest() != change["before_sha256"]:
                raise OSError("取消後の読み戻しに失敗しました")
            record = {"schema": 1, "job_id": job_id, "run_id": report["run_id"],
                      "path": change["path"], "restored_sha256": change["before_sha256"]}
            temporary_receipt = receipt.with_name("web-undo." + secrets.token_hex(8) + ".tmp")
            try:
                temporary_receipt.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
                os.replace(temporary_receipt, receipt)
            finally:
                temporary_receipt.unlink(missing_ok=True)
            return {"undone": True, "workspace": root, "job_id": job_id,
                    "path": change["path"], "sha256": change["before_sha256"]}

    def status(self, root, job_id):
        root = self._root(root)
        for attempt in range(3):
            try:
                with AgentQueue(root) as queue:
                    job = queue.get(job_id)
                break
            except ValueError as error:
                if str(error) != "path escapes workspace" or attempt == 2:
                    raise
                time.sleep(0.01)
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
        undone = self._undo_recorded(Workspace(root, create_audit=False), job_id, job["run_id"])
        return {"workspace": root, "job_id": job["id"], "status": job["status"],
                "run_id": job["run_id"], "cancel_requested": bool(job["cancel_requested"]),
                "error": job["error"] or worker_error, "summary": result.get("summary"),
                "changes": result.get("changes", []), "syntax_verified": result.get("syntax_verified"),
                "tests_passed": result.get("tests_passed"), "execution_enabled": result.get("execution_enabled", False),
                "acceptance": result.get("acceptance"), "events": events, "undone": undone}

