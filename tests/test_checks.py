from pathlib import Path

import yaml

from sentinel.codebase.checks import run_checks

ROOT = Path(__file__).resolve().parent.parent


def _lines(path: str) -> list[str]:
    return (ROOT / "demo-target-repo" / path).read_text().splitlines()


def test_static_checks_find_easy_violations_and_spare_decoys():
    golden = yaml.safe_load((ROOT / "evals" / "golden.yaml").read_text())
    hits = {(h.path, h.category, h.start_line) for h in run_checks(ROOT / "demo-target-repo")}

    def line_of(item):
        if "line" in item:
            return item["line"]
        return next(i for i, ln in enumerate(_lines(item["path"]), 1) if item["match"] in ln)

    easy = [v for v in golden["violations"] if v["difficulty"] == "easy"]
    missed = [v["id"] for v in easy if (v["path"], v["category"], line_of(v)) not in hits]
    assert missed == []
    alarms = [d["id"] for d in golden["decoys"] if (d["path"], d["category"], line_of(d)) in hits]
    assert alarms == []


def test_mitigations_suppress_line_rules(tmp_path):
    (tmp_path / "a.py").write_text(
        'log.info("user %s", redact(user.email))\n'
        'requests.get("http://localhost:8000/health")\n'
        'API_KEY = os.environ["API_KEY"]\n')
    line_hits = [h for h in run_checks(tmp_path) if h.snippet and not h.snippet.startswith("(whole")]
    assert line_hits == []


def test_span_rule_soft_delete(tmp_path):
    (tmp_path / "a.py").write_text(
        "def delete_user(u, db):\n    u.is_deleted = True\n    db.commit()\n\n"
        "def erase_user(u, db):\n    u.is_deleted = True\n    db.session.delete(u)\n")
    hits = [h for h in run_checks(tmp_path) if h.rule_id == "DEL001"]
    assert [h.start_line for h in hits] == [2]


def test_python_fallback_without_tree_sitter(monkeypatch):
    from sentinel.codebase import chunker

    monkeypatch.setattr(chunker, "_parser", lambda lang: None)
    spans = chunker.chunk_code("import x\n\n@app.get('/u')\ndef handler(u):\n    return u\n", "python")
    assert [(s.symbol, s.start_line, s.end_line) for s in spans] == [
        ("<module>", 1, 1), ("handler", 3, 5)]
    golden_hits = {(h.rule_id, h.path) for h in run_checks(ROOT / "demo-target-repo")}
    assert ("ACC001", "app/routes/users.py") in golden_hits
    assert ("DEL001", "app/routes/users.py") in golden_hits
