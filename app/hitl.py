"""Human-in-the-loop approval queue for fixes that become memory.

Rule (architecture-plan.md §5.1): ONLY a human-approved fix becomes memory.
Agents never approve their own fixes. An approved fix is written to Meko by
the harness (``memory_add``, with ``source: agent`` + ``approved_by`` in
metadata). A rejected fix goes to the audit log with its reason and is never
retried as a memory.

Storage: one JSON file (``results/hitl_queue.json``) with an audit trail.
The demo server reads/writes the same file, so the dashboard is the approval
surface for official runs.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

REJECT_REASONS = ("too_specific", "duplicate", "wrong_fix", "sensitive", "other")


@dataclass
class HITLItem:
    item_id: str
    ticket_id: str
    cluster: str
    memory_text: str
    metadata: dict
    status: str  # pending | approved | rejected
    proposed_by: str
    proposed_at: str
    decided_by: str = ""
    decided_at: str = ""
    reject_reason: str = ""
    note: str = ""


@dataclass
class HITLQueue:
    path: str | Path
    items: list[HITLItem] = field(default_factory=list)
    audit: list[dict] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.path = Path(self.path)
        if self.path.exists():
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self.items = [HITLItem(**it) for it in data.get("items", [])]
            self.audit = data.get("audit", [])

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps({"items": [asdict(i) for i in self.items], "audit": self.audit},
                       ensure_ascii=False, indent=2),
            encoding="utf-8")

    def refresh(self) -> None:
        """Re-read items/audit from disk.

        A long-running harness holds this queue in memory while an
        external approver (scripts/approve_pending.py, the chat flow)
        decides items in a separate process. Without a refresh,
        the next propose() would _save() the stale in-memory list and
        silently revert those decisions to pending. Call before propose().
        """
        if self.path.exists():
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self.items = [HITLItem(**it) for it in data.get("items", [])]
            self.audit = data.get("audit", [])

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    def propose(self, ticket_id: str, cluster: str, memory_text: str,
                metadata: dict, proposed_by: str = "agent") -> HITLItem:
        """Add a fix to the queue. Duplicate memory_text is a rejection case,
        not an auto-dedupe (the human decides)."""
        item = HITLItem(
            item_id=f"hitl-{uuid.uuid4().hex[:8]}",
            ticket_id=ticket_id, cluster=cluster, memory_text=memory_text,
            metadata=metadata, status="pending",
            proposed_by=proposed_by, proposed_at=self._now())
        self.items.append(item)
        self.audit.append({"event": "proposed", "item_id": item.item_id,
                           "ticket_id": ticket_id, "at": item.proposed_at,
                           "by": proposed_by})
        self._save()
        return item

    def approve(self, item_id: str, decided_by: str = "human") -> HITLItem | None:
        for item in self.items:
            if item.item_id == item_id and item.status == "pending":
                item.status = "approved"
                item.decided_by = decided_by
                item.decided_at = self._now()
                self.audit.append({"event": "approved", "item_id": item_id,
                                   "at": item.decided_at, "by": decided_by})
                self._save()
                return item
        return None

    def reject(self, item_id: str, reason: str, decided_by: str = "human") -> HITLItem | None:
        if reason not in REJECT_REASONS:
            raise ValueError(f"reject_reason must be one of {REJECT_REASONS}")
        for item in self.items:
            if item.item_id == item_id and item.status == "pending":
                item.status = "rejected"
                item.decided_by = decided_by
                item.decided_at = self._now()
                item.reject_reason = reason
                self.audit.append({"event": "rejected", "item_id": item_id,
                                   "reason": reason, "at": item.decided_at,
                                   "by": decided_by})
                self._save()
                return item
        return None

    def pending(self) -> list[HITLItem]:
        return [i for i in self.items if i.status == "pending"]

    def stats(self) -> dict:
        return {
            "pending": sum(1 for i in self.items if i.status == "pending"),
            "approved": sum(1 for i in self.items if i.status == "approved"),
            "rejected": sum(1 for i in self.items if i.status == "rejected"),
            "rejected_by_reason": {
                r: sum(1 for i in self.items if i.status == "rejected" and i.reject_reason == r)
                for r in REJECT_REASONS},
        }
