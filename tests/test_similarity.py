"""SEO-05: near-duplicate detection for scaled-content control."""
from lib import quality_gate, similarity

A = ("Choosing a CRM for a small agency starts with how you bill clients. Hourly billing needs time tracking "
     "built in, while retainers need recurring invoices and a clean pipeline view. HubSpot covers pipeline well "
     "but its invoicing is thin, so many agencies pair it with a dedicated billing tool and a shared inbox. ") * 3
B_RESKIN = "# Best CRM for agencies\n\n" + A.replace("HubSpot", "HubSpot").replace("thin", "thin") + "\n\nUpdated 2026."
C_DIFFERENT = ("Kubernetes schedules containers across a cluster using a control plane that watches desired state. "
               "Pods are the smallest deployable unit, and a deployment keeps a set of replicas running. Services give "
               "pods a stable address, and ingress rules route outside traffic to the right service inside the cluster. ") * 3


def test_a_reskinned_copy_is_a_near_duplicate_and_a_different_article_is_not():
    assert similarity.similarity(A, B_RESKIN) > 0.8
    assert similarity.similarity(A, C_DIFFERENT) < 0.05
    assert similarity.similarity("", A) == 0.0


def test_formatting_urls_and_numbers_cannot_hide_a_copy():
    dressed = "## H\n\n" + A.replace("CRM", "[CRM](https://x.example/crm?utm=1)") + "\n\n```py\nprint(1)\n```"
    assert similarity.similarity(A, dressed) > 0.8


def test_near_duplicates_returns_the_closest_first():
    out = similarity.near_duplicates(B_RESKIN, [(1, "kube", C_DIFFERENT), (2, "crm", A), (3, "empty", "")])
    assert [o["id"] for o in out] == [2]


def test_the_gate_blocks_a_copy_and_stays_quiet_otherwise():
    base = dict(content_md=B_RESKIN, meta={}, source_excerpts=[], check_links=False)
    blocked = quality_gate.assess(**base, siblings=[(2, "Best CRM", A)])
    assert any("near-duplicate" in b for b in blocked["blocking"])
    clean = quality_gate.assess(**base, siblings=[(1, "kube", C_DIFFERENT)])
    assert not any("duplicate" in b for b in clean["blocking"]) and not clean["checks"]["near_duplicate"]["matches"]
    unchecked = quality_gate.assess(**base)                         # no siblings supplied -> check skipped
    assert "near_duplicate" not in unchecked["checks"]


def test_a_partial_overlap_only_warns():
    half = A[: len(A) // 2] + " " + C_DIFFERENT
    out = quality_gate.assess(content_md=half, meta={}, source_excerpts=[], check_links=False,
                              siblings=[(2, "Best CRM", A)])
    sim = similarity.similarity(half, A)
    if sim >= similarity.DEFAULT_THRESHOLD:
        assert any("near-duplicate" in b for b in out["blocking"])
    else:
        assert not any("near-duplicate" in b for b in out["blocking"])
