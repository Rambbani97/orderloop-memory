"""Dataset integrity: 36 tickets, 8 clusters x 3, 3 distractors, 9 uniques,
valid memory_key pointers, no ground-truth leakage into ticket text, 12 KB
articles, ground-truth reference present."""

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"


def load_tickets():
    return [json.loads(line) for line in
            (DATA / "tickets.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()]


def test_ticket_counts():
    tickets = load_tickets()
    assert len(tickets) == 36
    ids = [t["id"] for t in tickets]
    assert len(set(ids)) == 36

    clusters = [t["cluster"] for t in tickets]
    for c in [f"C{i}" for i in range(1, 9)]:
        assert clusters.count(c) == 3, f"{c} should have 3 tickets"
    assert clusters.count("distractor") == 3
    assert clusters.count("unique") == 9
    assert sorted(t["id"] for t in tickets if t["cluster"] == "distractor") == [
        "D-01", "D-02", "D-03"]
    assert sorted(t["id"] for t in tickets if t["cluster"] == "unique") == [
        f"U-0{i}" for i in range(1, 10)]
    # distractors carry their look-alike target cluster
    targets = {t["id"]: t["target_cluster"] for t in tickets
               if t["cluster"] == "distractor"}
    assert targets == {"D-01": "C1", "D-02": "C2", "D-03": "C5"}


def test_memory_key_points_to_seed_of_same_cluster():
    tickets = load_tickets()
    by_id = {t["id"]: t for t in tickets}
    for t in tickets:
        if t.get("memory_key"):
            seed = by_id[t["memory_key"]]
            assert seed["cluster"] == t["cluster"]
            assert seed.get("memory_key") is None  # seeds point to nothing
    # exactly 16 repeats (2nd + 3rd of each of the 8 clusters)
    assert sum(1 for t in tickets if t.get("memory_key")) == 16


def test_no_leakage_between_tickets():
    """No ticket body/subject references another ticket's id (word boundary
    match — naive regex false-positives on order numbers like ORD-88412)."""
    tickets = load_tickets()
    ids = {t["id"] for t in tickets}
    for t in tickets:
        text = f"{t['subject']} {t['body']}"
        for other in ids - {t["id"]}:
            assert not re.search(rf"\b{re.escape(other)}\b", text), \
                f"{t['id']} leaks {other}"


def test_sanitize_strips_ground_truth():
    from app.agents import sanitize_ticket

    tickets = load_tickets()
    for t in tickets:
        view = sanitize_ticket(t)
        assert "root_cause" not in view
        assert "correct_fix" not in view
        assert "memory_key" not in view
        assert "target_cluster" not in view
        assert "wrong_fix" not in view
        assert view["id"] == t["id"]
        assert view["subject"] == t["subject"]


def test_kb_articles():
    articles = sorted((DATA / "kb").glob("kb-*.md"))
    assert len(articles) == 12
    for path in articles:
        assert path.stat().st_size > 200, f"{path.name} looks empty"


def test_ground_truth_reference_exists():
    gt = DATA / "ground_truth.md"
    assert gt.exists()
    text = gt.read_text(encoding="utf-8")
    # Cluster tickets are T-001..T-024; distractors D-01..D-03; uniques U-01..U-09.
    for tid in [f"T-{i:03d}" for i in range(1, 25)] + \
               [f"D-0{i}" for i in range(1, 4)] + \
               [f"U-0{i}" for i in range(1, 10)]:
        assert tid in text
