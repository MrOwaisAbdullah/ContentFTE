"""perspective param on _build_query_endpoint.

Probe-confirmed live (2026-10-06, apiVersion v2026-07-28): drafts.* docs
are invisible to id queries without perspective=raw, while mutate/delete
still see them. Default must therefore be raw for doc lookups; live-site
pools (internal links, lists, link hygiene) pin published explicitly.
"""
import urllib.parse

from lib.sanity_adapter import SanityAdapter


def _adapter():
    return SanityAdapter(project_id="x", dataset="y", token="z")


def test_default_perspective_is_raw():
    ep = _adapter()._build_query_endpoint("*[_id == $id]", {"id": "drafts.a"})
    assert "&perspective=raw" in ep


def test_perspective_published_override():
    ep = _adapter()._build_query_endpoint("*[_type == \"post\"]", perspective="published")
    assert "&perspective=published" in ep


def test_perspective_none_omits_param():
    ep = _adapter()._build_query_endpoint("*[_type == \"post\"]", perspective=None)
    assert "perspective" not in ep


def test_params_and_perspective_coexist():
    ep = _adapter()._build_query_endpoint(
        "*[_id == $id]{content}", {"id": "drafts.a"})
    assert '$id=%22drafts.a%22' in ep
    assert "&perspective=raw" in ep
    # query itself must keep the $id placeholder, not the value
    query_part = ep.split("query=", 1)[1].split("&")[0]
    assert "$id" in urllib.parse.unquote(query_part)


def test_live_site_pools_request_published():
    from tools.linkguard_tool import _fetch_all_hrefs

    class FakeAdapter:
        def __init__(self):
            self.last_endpoint = None

        def _build_query_endpoint(self, query, params, perspective=None):
            self.last_endpoint = f"perspective={perspective}"
            return "/x"

        def _make_request(self, *a, **k):
            raise AssertionError("should not reach network in URL check")

    # _fetch_all_hrefs calls raise_for_status on response; we only care the
    # URL builder was asked for published, so catch after the endpoint call.
    fake = FakeAdapter()
    try:
        _fetch_all_hrefs(fake)
    except Exception:
        pass
    assert fake.last_endpoint == "perspective=published"
