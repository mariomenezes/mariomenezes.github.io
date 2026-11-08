"""Contrato do laboratório do Flagger real (comparação v6). Sem cluster."""
import os
import sys
import unittest
from unittest import mock

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "probes"))

import prom  # noqa: E402


class PromSelectorTest(unittest.TestCase):
    def test_default_selector_is_the_lab_one(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            for k in ("TRIAGE_PROM_JOB", "TRIAGE_PROM_NAMESPACE", "TRIAGE_PROM_SERVICE"):
                os.environ.pop(k, None)
            s = prom._selector()
        self.assertIn('job="probe-generator"', s)
        self.assertIn('destination_service_namespace="lab-apps"', s)
        self.assertIn('destination_service_name="app-service"', s)
        self.assertIn('reporter="source"', s)

    def test_env_overrides_job_namespace_and_service_regex(self):
        env = {"TRIAGE_PROM_JOB": "probe-flagger", "TRIAGE_PROM_NAMESPACE": "flagger-lab",
               "TRIAGE_PROM_SERVICE": "app-fl.*"}
        with mock.patch.dict(os.environ, env):
            s = prom._selector()
        self.assertIn('job="probe-flagger"', s)
        self.assertIn('destination_service_namespace="flagger-lab"', s)
        self.assertIn('destination_service_name=~"app-fl.*"', s)
        self.assertNotIn("app-service", s)


class ProbeHeaderTest(unittest.TestCase):
    def headers(self, ratio):
        import probe_generator as pg
        seen = []

        def fake_urlopen(req, timeout=0):
            seen.append(dict(req.header_items()))
            raise pg.URLError("x")  # não precisa de resposta
        with mock.patch.object(pg, "urlopen", fake_urlopen), mock.patch.object(pg, "record", lambda r: None), \
                mock.patch.object(pg, "CANARY_HEADER_RATIO", ratio):
            for _ in range(200):
                pg.probe_once()
        return seen

    def test_ratio_zero_never_adds_the_header(self):
        self.assertTrue(all("X-canary" not in h for h in self.headers(0.0)))

    def test_ratio_one_always_adds_it(self):
        self.assertTrue(all(h.get("X-canary") == "insider" for h in self.headers(1.0)))

    def test_ratio_half_is_about_half(self):
        n = sum(1 for h in self.headers(0.5) if "X-canary" in h)
        self.assertTrue(70 <= n <= 130, n)


def load(name):
    with open(os.path.join(HERE, "flagger", name), encoding="utf-8") as f:
        return [d for d in yaml.safe_load_all(f) if d]


class ManifestTest(unittest.TestCase):
    def kinds(self, name):
        return {d["kind"]: d for d in load(name)}

    def test_canary_is_ab_with_the_frozen_analysis(self):
        c = self.kinds("canary.yaml")["Canary"]
        a = c["spec"]["analysis"]
        self.assertEqual((a["interval"], a["iterations"], a["threshold"]), ("1m", 16, 5))
        self.assertEqual(a["match"], [{"headers": {"x-canary": {"exact": "insider"}}}])
        self.assertNotIn("maxWeight", a)
        self.assertNotIn("stepWeight", a)
        names = {m["name"]: m for m in a["metrics"]}
        self.assertEqual(names["request-success-rate"]["thresholdRange"], {"min": 99})
        self.assertEqual(names["p99-ratio"]["thresholdRange"], {"max": 1.15})
        self.assertEqual(names["p99-ratio"]["templateRef"]["name"], "p99-ratio")
        self.assertEqual(len(a["metrics"]), 2)

    def test_canary_keeps_the_lab_retry_and_timeout(self):
        s = self.kinds("canary.yaml")["Canary"]["spec"]
        self.assertEqual(s["service"]["timeout"], "10s")
        self.assertEqual(s["service"]["retries"]["attempts"], 2)
        self.assertEqual(s["service"]["retries"]["perTryTimeout"], "5s")
        self.assertEqual(s["targetRef"]["name"], "app-fl")
        self.assertEqual(s["service"]["port"], 8080)

    def test_metric_template_compares_the_canary_with_the_primary_p99(self):
        t = self.kinds("canary.yaml")["MetricTemplate"]
        q = t["spec"]["query"]
        self.assertEqual(t["spec"]["provider"]["address"], "http://prometheus.observability:9090")
        self.assertIn("histogram_quantile(0.99", q)
        self.assertIn('destination_workload="{{ target }}-primary"', q)
        self.assertIn('destination_workload="{{ target }}"', q)
        self.assertIn("{{ interval }}", q)
        self.assertEqual(q.count("rate("), 2)
        self.assertNotIn("irate", q)
        self.assertIn('reporter="destination"', q)

    def test_app_matches_the_lab_environment(self):
        d = self.kinds("app.yaml")["Deployment"]
        c = d["spec"]["template"]["spec"]["containers"][0]
        env = {e["name"]: e["value"] for e in c["env"]}
        self.assertEqual(env["SLOW_DELAY_S"], "3")
        self.assertEqual(env["SLOW_JITTER_SIGMA"], "0.1")
        self.assertEqual(d["spec"]["replicas"], 1)
        self.assertEqual(d["spec"]["template"]["metadata"]["annotations"]["sidecar.istio.io/inject"], "true")

    def test_load_generator_has_the_lab_mix_and_the_ab_header(self):
        docs = self.kinds("loadgen.yaml")
        env = {e["name"]: e["value"] for e in
               docs["Deployment"]["spec"]["template"]["spec"]["containers"][0]["env"]}
        self.assertEqual(env["APP_URL"], "http://app-fl.flagger-lab.svc.cluster.local:8080")
        self.assertEqual((env["PROBE_INTERVAL"], env["WORKERS"], env["CANARY_HEADER_RATIO"]), ("1", "8", "0.5"))
        self.assertEqual(docs["Deployment"]["spec"]["replicas"], 2)
        ann = docs["Deployment"]["spec"]["template"]["metadata"]["annotations"]
        self.assertIn("feature", ann["proxy.istio.io/config"])
        self.assertIn("3750", ann["sidecar.istio.io/statsHistogramBuckets"])
        t = docs["Telemetry"]
        self.assertEqual(t["metadata"]["namespace"], "flagger-lab")

    def test_prometheus_job_maps_workload_to_revision(self):
        jobs = {j["job_name"]: j for j in load("prometheus-jobs.yaml")[0]}
        self.assertEqual(set(jobs), {"probe-flagger", "app-flagger"})
        job = jobs["probe-flagger"]
        self.assertEqual(jobs["app-flagger"]["kubernetes_sd_configs"][0]["namespaces"]["names"], ["flagger-lab"])
        rel = job["metric_relabel_configs"]
        flat = yaml.safe_dump(rel)
        self.assertIn("destination_canonical_revision", flat)
        self.assertIn("-primary", flat)
        self.assertEqual(job["kubernetes_sd_configs"][0]["namespaces"]["names"], ["flagger-lab"])


if __name__ == "__main__":
    unittest.main()
