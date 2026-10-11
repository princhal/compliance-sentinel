import uuid

from sentinel.auth.clerk import principal_from_claims
from sentinel.embeddings import HashEmbedder
from sentinel.llm import EvidenceItem, HeuristicEngine, ObligationView, _flagged_text
from sentinel.rag.retriever import rrf_merge


def test_clerk_v2_claims_nest_the_org():
    p = principal_from_claims({"sub": "user_1", "v": 2,
                               "o": {"id": "org_1", "rol": "admin", "per": "audit:approve"}})
    assert (p.user_id, p.org_id, p.role) == ("user_1", "org_1", "org:admin")
    assert p.permissions == ["org:audit:approve"]


def test_clerk_v1_claims_are_flat():
    p = principal_from_claims({"sub": "user_1", "org_id": "org_2", "org_role": "org:auditor"})
    assert (p.org_id, p.role) == ("org_2", "org:auditor")


def test_clerk_claims_without_org():
    assert principal_from_claims({"sub": "user_1"}).org_id is None


def test_weighted_rrf():
    a, b, c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    scores = rrf_merge([[a, b], [b, c]], [1.0, 1.0])
    assert max(scores, key=scores.get) == b
    # An item found by both retrievers beats a single strong hit...
    scores = rrf_merge([[a, b], [c, b]], [0.1, 1.0])
    assert max(scores, key=scores.get) == b
    # ...and a low weight shrinks a retriever's influence.
    scores = rrf_merge([[a], [c]], [0.1, 1.0])
    assert max(scores, key=scores.get) == c


def test_hash_embedder_is_deterministic_and_normalized():
    e = HashEmbedder()
    v1, v2 = e.embed_query("encrypt personal data", "law"), e.embed_query("encrypt personal data", "law")
    assert v1 == v2 and abs(sum(x * x for x in v1) - 1.0) < 1e-6
    assert len(v1) == 1024


def test_heuristic_extraction_uses_word_pairs():
    eng = HeuristicEngine()
    drafts = eng.extract_obligations(
        "CCPA", "§ 1798.105(c)(1)", "",
        "A business shall delete the consumer's personal information from its records, notify "
        "any service providers or contractors to delete the consumer's personal information.")
    cats = {d.category for d in drafts}
    assert "data_deletion" in cats and "breach_notification" not in cats


def test_heuristic_assess_ignores_padding_lines():
    ev = EvidenceItem(id="E1", path="a.py", start_line=11, end_line=11,
                      snippet='   10 | x = 1\n   11 | requests.post("http://a.io", verify=False)\n'
                              '   12 | requests.get("https://b.io")',
                      source="TLS002", message="TLS off", rule_confidence=0.9)
    assert "https" not in _flagged_text(ev)
    ob = ObligationView("GDPR", "Art. 32(1)", "encryption_in_transit", "high", "s", "q")
    [item] = HeuristicEngine().assess(ob, [ev])
    assert item.status == "violation"


def test_extraction_gate_skips_text_without_duties_or_privacy():
    from sentinel.ingest.chunker import Chunk
    from sentinel.ingest.pipeline import worth_extracting

    duty_privacy = Chunk("US-FR para 1", "", "Carriers must protect personal information of riders.", "")
    duty_only = Chunk("US-FR para 2", "", "Carriers must post timetables at each station.", "")
    no_duty = Chunk("GDPR Art. 4(1)", "", "'personal data' means any information relating to a person;", "")
    assert worth_extracting(duty_privacy, "US-FR")
    assert not worth_extracting(duty_only, "US-FR")
    assert not worth_extracting(no_duty, "GDPR")
    assert worth_extracting(Chunk("GDPR Art. 7(1)", "", "The controller shall be able to demonstrate.", ""),
                            "GDPR")


def test_section_refs_sort_by_number_not_text():
    from sentinel.api.app import section_sort_key

    refs = ["GDPR Art. 44", "GDPR Art. 5(1)(f)", "GDPR Art. 32(3a)", "GDPR Art. 5(1)(c)", "GDPR Art. 32(1)",
            "CCPA § 1798.105(c)(1)", "CCPA § 1798.100(e)"]
    assert sorted(refs, key=section_sort_key) == [
        "CCPA § 1798.100(e)", "CCPA § 1798.105(c)(1)", "GDPR Art. 5(1)(c)", "GDPR Art. 5(1)(f)",
        "GDPR Art. 32(1)", "GDPR Art. 32(3a)", "GDPR Art. 44"]
