import unittest
from urllib.parse import parse_qs, urlparse

from prom import (PromClient, bucket_query, build_url, parse_buckets, slow_count)


def vec(rows):
    return {"status": "success", "data": {"result": [
        {"metric": {"destination_canonical_revision": v, "feature": f}, "value": [0, val]}
        for (v, f), val in rows.items()]}}


def bucket_payload():
    def row(v, f, le, val):
        return {"metric": {"destination_canonical_revision": v, "feature": f, "le": le},
                "value": [0, val]}
    return {"status": "success", "data": {"result": [
        row("v2", "dashboard", "100", "70"), row("v2", "dashboard", "250", "80"),
        row("v2", "dashboard", "500", "95"), row("v2", "dashboard", "+Inf", "100"),
        row("v1", "dashboard", "100", "99"), row("v1", "dashboard", "250", "100"),
        row("v1", "dashboard", "+Inf", "100"),
    ]}}


class BuildUrlTest(unittest.TestCase):
    def test_without_time_has_no_time_param(self):
        q = parse_qs(urlparse(build_url("http://x:9/", "up")).query)
        self.assertEqual(q, {"query": ["up"]})

    def test_with_time_adds_it(self):
        q = parse_qs(urlparse(build_url("http://x:9", "up", 1761000000.5)).query)
        self.assertEqual(q["time"], ["1761000000.5"])

    def test_trailing_slash_is_stripped(self):
        self.assertTrue(build_url("http://x:9/", "up").startswith("http://x:9/api/v1/query?"))


class BucketQueryTest(unittest.TestCase):
    def test_groups_by_version_feature_and_le(self):
        q = bucket_query()
        self.assertIn("sum by (destination_canonical_revision, feature, le)", q)
        self.assertIn("increase(istio_request_duration_milliseconds_bucket", q)
        self.assertIn('reporter="source"', q)
        self.assertIn("[1m]", q)


class ParseBucketsTest(unittest.TestCase):
    def test_groups_cumulative_counts_by_key(self):
        b = parse_buckets(bucket_payload())
        self.assertEqual(b[("v2", "dashboard")], {"100": 70.0, "250": 80.0, "500": 95.0, "+Inf": 100.0})
        self.assertEqual(set(b), {("v2", "dashboard"), ("v1", "dashboard")})

    def test_error_payload_raises(self):
        with self.assertRaises(ValueError):
            parse_buckets({"status": "error", "error": "boom"})


class SlowCountTest(unittest.TestCase):
    def setUp(self):
        self.b = parse_buckets(bucket_payload())

    def test_counts_requests_above_limit(self):
        self.assertEqual(slow_count(self.b[("v2", "dashboard")], 250), (100, 20))
        self.assertEqual(slow_count(self.b[("v2", "dashboard")], 100), (100, 30))
        self.assertEqual(slow_count(self.b[("v1", "dashboard")], 250), (100, 0))

    def test_limit_must_be_an_existing_bucket_edge(self):
        with self.assertRaises(KeyError):
            slow_count(self.b[("v2", "dashboard")], 300)

    def test_accepts_float_edge_formatting(self):
        self.assertEqual(slow_count({"250": 5.0, "+Inf": 8.0}, 250.0), (8, 3))
        self.assertEqual(slow_count({"0.5": 1.0, "+Inf": 4.0}, 0.5), (4, 3))

    def test_missing_inf_bucket_raises(self):
        with self.assertRaises(KeyError):
            slow_count({"250": 5.0}, 250)


class TimeThreadingTest(unittest.TestCase):
    def test_at_is_forwarded_to_every_query(self):
        seen = []

        class Fake(PromClient):
            def query(self, promql, at=None):
                seen.append(at)
                if "_bucket" in promql and "histogram_quantile" not in promql:
                    return bucket_payload()
                return vec({("v2", "dashboard"): "60"})

        Fake("http://x").windows(at=123.0)
        self.assertTrue(seen and all(a == 123.0 for a in seen), seen)
        seen.clear()
        Fake("http://x").buckets(at=456.0)
        self.assertEqual(seen, [456.0])

    def test_single_argument_query_override_still_works_without_at(self):
        class Old(PromClient):  # como em test_agent.py: query(self, promql)
            def query(self, promql):
                return vec({("v2", "dashboard"): "60"})

        w = Old("http://x").windows()
        self.assertEqual(w[("v2", "dashboard")].n, 60)


if __name__ == "__main__":
    unittest.main()
