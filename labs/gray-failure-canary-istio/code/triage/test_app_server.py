import json
import os
import sys
import threading
import time
import unittest
import urllib.error
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app"))
import app_server  # noqa: E402
from app_server import FaultState, build_servers, parse_fault  # noqa: E402

BASE0 = {"slow_extra_fraction": 0.0, "slow_extra_s": 0.0, "fast_delay_fraction": 0.0, "fast_delay_s": 0.0}


class FakeClock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


class ParseFaultTest(unittest.TestCase):
    def test_valid_body(self):
        p, ttl = parse_fault({"slow_extra_fraction": 0.2, "slow_extra_s": 1.5, "ttl_s": 720})
        self.assertEqual(p, {**BASE0, "slow_extra_fraction": 0.2, "slow_extra_s": 1.5})
        self.assertEqual(ttl, 720)

    def test_missing_params_default_to_zero(self):
        p, _ = parse_fault({"fast_delay_fraction": 0.2, "fast_delay_s": 0.5, "ttl_s": 60})
        self.assertEqual(p["slow_extra_fraction"], 0.0)

    def test_all_zero_needs_no_ttl(self):
        p, ttl = parse_fault({})
        self.assertEqual((p, ttl), (BASE0, None))

    def test_ttl_is_required_when_any_param_is_nonzero(self):
        with self.assertRaisesRegex(ValueError, "ttl_s"):
            parse_fault({"slow_extra_fraction": 0.2, "slow_extra_s": 1.5})

    def test_ttl_range(self):
        for ttl in (0, -5, 3601, "10", True):
            with self.assertRaises(ValueError, msg=ttl):
                parse_fault({"slow_extra_fraction": 0.2, "slow_extra_s": 1.5, "ttl_s": ttl})
        parse_fault({"slow_extra_fraction": 0.2, "slow_extra_s": 1.5, "ttl_s": 3600})

    def test_rejects_unknown_keys(self):
        with self.assertRaisesRegex(ValueError, "desconhecid"):
            parse_fault({"slow_fraction": 0.2, "ttl_s": 60})

    def test_rejects_out_of_range_and_non_numbers(self):
        for body in ({"slow_extra_fraction": 1.5}, {"slow_extra_fraction": -0.1},
                     {"slow_extra_s": 31}, {"fast_delay_s": -1},
                     {"slow_extra_fraction": "0.2"}, {"slow_extra_fraction": True},
                     {"slow_extra_fraction": float("nan")}):
            with self.assertRaises(ValueError, msg=body):
                parse_fault({**body, "ttl_s": 60})

    def test_body_must_be_an_object(self):
        with self.assertRaises(ValueError):
            parse_fault([1, 2])


class FaultStateTest(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.st = FaultState(BASE0, clock=self.clock)

    def test_default_is_the_base_and_inactive(self):
        self.assertEqual(self.st.current(), BASE0)
        s = self.st.snapshot()
        self.assertFalse(s["active"])
        self.assertIsNone(s["expires_at"])

    def test_set_overrides_until_ttl_then_returns_to_base(self):
        self.st.set({**BASE0, "slow_extra_fraction": 0.2, "slow_extra_s": 1.5}, ttl_s=720)
        self.assertEqual(self.st.current()["slow_extra_fraction"], 0.2)
        self.assertTrue(self.st.snapshot()["active"])
        self.clock.t += 719.9
        self.assertEqual(self.st.current()["slow_extra_fraction"], 0.2)
        self.clock.t += 0.2
        self.assertEqual(self.st.current(), BASE0)
        self.assertEqual([h["event"] for h in self.st.snapshot()["history"]], ["set", "expired"])

    def test_expiry_is_recorded_with_the_real_expiry_time(self):
        self.st.set({**BASE0, "fast_delay_fraction": 0.2, "fast_delay_s": 0.5}, ttl_s=60)
        self.clock.t += 500
        self.st.current()
        exp = self.st.snapshot()["history"][-1]
        self.assertEqual(exp["event"], "expired")
        self.assertEqual(exp["at"], 1060.0)

    def test_clear_returns_to_base_and_is_logged(self):
        self.st.set({**BASE0, "slow_extra_fraction": 0.2, "slow_extra_s": 1.5}, ttl_s=720)
        self.st.clear()
        self.assertEqual(self.st.current(), BASE0)
        self.assertEqual([h["event"] for h in self.st.snapshot()["history"]], ["set", "clear"])

    def test_clear_when_idle_adds_no_history(self):
        self.st.clear()
        self.assertEqual(self.st.snapshot()["history"], [])

    def test_override_wins_over_a_nonzero_env_base_and_base_returns_after(self):
        base = {**BASE0, "slow_extra_fraction": 0.5, "slow_extra_s": 1.0}
        st = FaultState(base, clock=self.clock)
        st.set({**BASE0, "slow_extra_fraction": 0.1, "slow_extra_s": 2.0}, ttl_s=60)
        self.assertEqual(st.current()["slow_extra_fraction"], 0.1)
        self.clock.t += 61
        self.assertEqual(st.current(), base)

    def test_set_replaces_a_previous_override(self):
        self.st.set({**BASE0, "slow_extra_fraction": 0.2, "slow_extra_s": 1.5}, ttl_s=60)
        self.st.set({**BASE0, "slow_extra_fraction": 0.1, "slow_extra_s": 1.5}, ttl_s=600)
        self.assertEqual(self.st.current()["slow_extra_fraction"], 0.1)
        self.assertEqual(self.st.snapshot()["expires_at"], 1600.0)

    def test_history_is_bounded(self):
        for _ in range(60):
            self.st.set({**BASE0, "slow_extra_fraction": 0.2, "slow_extra_s": 1.5}, ttl_s=60)
        self.assertLessEqual(len(self.st.snapshot()["history"]), 50)

    def test_change_counter_is_monotonic_beyond_the_history_cap(self):
        self.assertEqual(self.st.snapshot()["changes"], 0)
        for i in range(60):
            self.st.set({**BASE0, "slow_extra_fraction": 0.2, "slow_extra_s": 1.5}, ttl_s=60)
            self.assertEqual(self.st.snapshot()["changes"], i + 1)
        self.assertEqual(len(self.st.snapshot()["history"]), 50)

    def test_change_counter_counts_clear_and_expiry_but_not_idle_clear(self):
        self.st.clear()
        self.assertEqual(self.st.snapshot()["changes"], 0)
        self.st.set({**BASE0, "slow_extra_fraction": 0.2, "slow_extra_s": 1.5}, ttl_s=60)
        self.st.clear()
        self.assertEqual(self.st.snapshot()["changes"], 2)
        self.st.set({**BASE0, "slow_extra_fraction": 0.2, "slow_extra_s": 1.5}, ttl_s=60)
        self.clock.t += 61
        self.assertEqual(self.st.snapshot()["changes"], 4)


class Http:
    """Sobe os dois servidores em portas efêmeras e fala com eles."""

    def __init__(self, st):
        self.main, self.admin = build_servers(st, port=0, admin_port=0, host="127.0.0.1")
        for srv in (self.main, self.admin):
            threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()
        self.mp, self.ap = self.main.server_address[1], self.admin.server_address[1]

    def close(self):
        for srv in (self.main, self.admin):
            srv.shutdown()
            srv.server_close()

    def call(self, port, method, path, body=None):
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data, method=method)
        t0 = time.monotonic()

        def parse(raw):  # a porta principal responde HTML a métodos que não implementa
            try:
                return json.loads(raw or b"{}")
            except ValueError:
                return {"raw": raw[:60].decode("utf-8", "replace")}

        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, parse(r.read()), time.monotonic() - t0
        except urllib.error.HTTPError as e:
            try:
                return e.code, parse(e.read()), time.monotonic() - t0
            finally:
                e.close()


class HttpTest(unittest.TestCase):
    def setUp(self):
        self._delay = app_server.SLOW_DELAY_S
        app_server.SLOW_DELAY_S = 0.0
        self.clock = FakeClock()
        self.h = Http(FaultState(BASE0, clock=self.clock))

    def tearDown(self):
        self.h.close()
        app_server.SLOW_DELAY_S = self._delay

    def test_admin_is_not_reachable_on_the_service_port(self):
        for method in ("GET", "PUT", "DELETE"):
            code, _, _ = self.h.call(self.h.mp, method, "/admin/fault", {} if method == "PUT" else None)
            self.assertIn(code, (404, 501), method)

    def test_admin_binds_to_loopback_only(self):
        self.assertEqual(self.h.admin.server_address[0], "127.0.0.1")

    def test_service_endpoints_still_work(self):
        code, body, _ = self.h.call(self.h.mp, "GET", "/healthz")
        self.assertEqual((code, body), (200, {"status": "ok"}))
        code, body, _ = self.h.call(self.h.mp, "GET", "/api/v1/fast-data")
        self.assertEqual((code, body["kind"]), (200, "fast"))

    def test_put_then_read_back(self):
        code, body, _ = self.h.call(self.h.ap, "PUT", "/admin/fault",
                                    {"slow_extra_fraction": 0.2, "slow_extra_s": 1.5, "ttl_s": 720})
        self.assertEqual(code, 200)
        self.assertTrue(body["active"])
        code, body, _ = self.h.call(self.h.ap, "GET", "/admin/fault")
        self.assertEqual(body["params"]["slow_extra_fraction"], 0.2)
        self.assertEqual(body["expires_at"], 1720.0)
        self.assertEqual(body["history"][0]["event"], "set")

    def test_invalid_body_is_400_and_changes_nothing(self):
        code, body, _ = self.h.call(self.h.ap, "PUT", "/admin/fault", {"slow_extra_fraction": 2, "ttl_s": 60})
        self.assertEqual(code, 400)
        self.assertIn("error", body)
        _, state, _ = self.h.call(self.h.ap, "GET", "/admin/fault")
        self.assertFalse(state["active"])
        self.assertEqual(state["history"], [])

    def test_malformed_json_is_400(self):
        req = urllib.request.Request(f"http://127.0.0.1:{self.h.ap}/admin/fault", data=b"{no", method="PUT")
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(req, timeout=5)
        self.assertEqual(cm.exception.code, 400)
        cm.exception.close()

    def test_delete_clears(self):
        self.h.call(self.h.ap, "PUT", "/admin/fault", {"slow_extra_fraction": 1, "slow_extra_s": 1, "ttl_s": 60})
        code, body, _ = self.h.call(self.h.ap, "DELETE", "/admin/fault")
        self.assertEqual(code, 200)
        self.assertFalse(body["active"])

    def test_slow_fault_delays_slow_data_and_ttl_restores_it(self):
        self.h.call(self.h.ap, "PUT", "/admin/fault", {"slow_extra_fraction": 1.0, "slow_extra_s": 0.3, "ttl_s": 60})
        _, _, dt = self.h.call(self.h.mp, "GET", "/api/v1/slow-data")
        self.assertGreaterEqual(dt, 0.3)
        self.clock.t += 61  # o prazo vence sem ninguém chamar o endpoint admin
        _, _, dt = self.h.call(self.h.mp, "GET", "/api/v1/slow-data")
        self.assertLess(dt, 0.2)

    def test_fast_fault_delays_fast_data_only_for_that_feature(self):
        self.h.call(self.h.ap, "PUT", "/admin/fault", {"fast_delay_fraction": 1.0, "fast_delay_s": 0.3, "ttl_s": 60})
        _, _, dt = self.h.call(self.h.mp, "GET", "/api/v1/fast-data")
        self.assertGreaterEqual(dt, 0.3)
        _, _, dt = self.h.call(self.h.mp, "GET", "/api/v1/slow-data")
        self.assertLess(dt, 0.2)

    def test_fraction_zero_never_delays(self):
        self.h.call(self.h.ap, "PUT", "/admin/fault", {"slow_extra_fraction": 0.0, "slow_extra_s": 5, "ttl_s": 60})
        _, _, dt = self.h.call(self.h.mp, "GET", "/api/v1/slow-data")
        self.assertLess(dt, 0.2)


class EnvBaseTest(unittest.TestCase):
    def test_env_values_are_the_base_without_override(self):
        app_server.SLOW_DELAY_S, old = 0.0, app_server.SLOW_DELAY_S
        try:
            base = {**BASE0, "slow_extra_fraction": 1.0, "slow_extra_s": 0.25}
            h = Http(FaultState(base, clock=FakeClock()))
            try:
                _, _, dt = h.call(h.mp, "GET", "/api/v1/slow-data")
                self.assertGreaterEqual(dt, 0.25)
            finally:
                h.close()
        finally:
            app_server.SLOW_DELAY_S = old

    def test_module_base_reads_the_existing_env_variables(self):
        b = app_server.base_from_env({"SLOW_EXTRA_FRACTION": "0.2", "SLOW_EXTRA_S": "1.5",
                                      "FAST_DELAY_FRACTION": "0.1", "FAST_DELAY_S": "0.5"})
        self.assertEqual(b, {"slow_extra_fraction": 0.2, "slow_extra_s": 1.5,
                             "fast_delay_fraction": 0.1, "fast_delay_s": 0.5})
        self.assertEqual(app_server.base_from_env({}), BASE0)


if __name__ == "__main__":
    unittest.main()
