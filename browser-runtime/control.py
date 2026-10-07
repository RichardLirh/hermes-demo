"""Serialize browser operations and fence stale agent/user commands.

Authorization of the HTTP caller belongs to the adapter. Pass the authenticated
owner, never an owner copied blindly from a request body. Only this object may
hold the browser driver; exposing raw CDP to another writer bypasses the fence.
"""
from dataclasses import dataclass
from hashlib import sha256
from threading import RLock
from time import monotonic
from uuid import uuid4
import json


class Rejected(RuntimeError):
    pass


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


@dataclass
class Approval:
    draft: str
    epoch: int
    expires: float


class SessionControl:
    def __init__(self, owner, run_id, sandbox_id, browser_session_id, clock=monotonic):
        self.owner = owner
        self.run_id = run_id
        self.sandbox_id = sandbox_id
        self.browser_session_id = browser_session_id
        self.clock = clock
        self.mode = "AGENT"
        self.epoch = 1
        self.closed = False
        self.lock = RLock()
        self.approvals = {}
        self.receipts = {}

    def _check(self, owner, epoch, mode=None):
        if owner != self.owner or self.closed:
            raise Rejected("Unknown owner or closed session")
        if epoch != self.epoch:
            raise Rejected("Stale control version")
        if mode is not None and self.mode != mode:
            raise Rejected("Caller does not hold browser control")

    def snapshot(self):
        with self.lock:
            return dict(runId=self.run_id, sandboxId=self.sandbox_id,
                        browserSessionId=self.browser_session_id,
                        mode=self.mode, epoch=self.epoch, closed=self.closed)

    def transfer(self, owner, epoch, target):
        if target not in ("AGENT", "USER"):
            raise Rejected("Invalid control target")
        # Wait for the current operation to finish before acknowledging handoff.
        with self.lock:
            self._check(owner, epoch)
            if target == self.mode:
                raise Rejected("Control already held")
            self.mode = target
            self.epoch += 1
            self.approvals.clear()
            return self.snapshot()

    def operate(self, owner, epoch, actor, operation):
        with self.lock:
            self._check(owner, epoch, actor)
            return operation()

    def approve(self, owner, epoch, draft, ttl=120):
        with self.lock:
            self._check(owner, epoch)
            if not 0 < ttl <= 300:
                raise Rejected("Approval TTL must be 1..300 seconds")
            token = str(uuid4())
            self.approvals[token] = Approval(digest(draft), epoch, self.clock() + ttl)
            return token

    def submit(self, owner, epoch, actor, token, draft, operation_id, operation):
        with self.lock:
            self._check(owner, epoch, actor)
            fingerprint = digest(draft)
            if operation_id in self.receipts:
                previous = self.receipts[operation_id]
                if previous[0] != fingerprint:
                    raise Rejected("Operation ID reused for a different draft")
                if previous[1] != "completed":
                    raise Rejected("Submission outcome uncertain; reconcile before retry")
                return previous[2]
            approval = self.approvals.pop(token, None)
            if not approval or approval.epoch != epoch or approval.draft != fingerprint:
                raise Rejected("Missing or mismatched approval")
            if self.clock() >= approval.expires:
                raise Rejected("Expired approval")
            # Mark before external mutation: errors must not silently replay it.
            self.receipts[operation_id] = (fingerprint, "pending", None)
            result = operation()
            self.receipts[operation_id] = (fingerprint, "completed", result)
            return result

    def close(self, owner, epoch):
        with self.lock:
            self._check(owner, epoch)
            self.closed = True
            self.epoch += 1
            self.approvals.clear()
