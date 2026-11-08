"""O replay (via ShadowAgent) reproduz os números já publicados nos RESUMOs.

Se algum destes testes falhar, PARE e investigue: ou o replay está errado, ou o RESUMO
estava. Não ajuste o teste ao resultado. Os dados vêm de triage/results/ (versionados).
"""
import glob
import os
import re
import unittest
from collections import defaultdict

from analyze_noise import agent_events, with_ratio
from replay import first_detected, load_samples, replay

HERE = os.path.dirname(os.path.abspath(__file__))
FAULT_START = 4  # a falha liga na janela 5 do arquivo; depois do skip=1 é o índice 4


def files(pattern):
    found = sorted(glob.glob(os.path.join(HERE, pattern)))
    if not found:
        raise unittest.SkipTest(f"sem dados em {pattern}")
    return found


def hit_table(pattern, group, configs, feature="heavy-reports"):
    """grupo -> rótulo -> [detecções na falha, alarmes antes da falha, violações de isolamento, n]."""
    rows = defaultdict(lambda: defaultdict(lambda: [0, 0, 0, 0]))
    for p in files(pattern):
        ld = load_samples(p)
        assert ld.duplicates == 0 and ld.errors == 0, p
        for label, rule, ratio, watch in configs:
            r = replay(ld.samples, "x", rule, ratio, 1)
            assert not r.gaps, p
            ev, kind = (r.watch, "c_detected") if watch else (r.events, "detected")
            idx = next((i for i, f, k in ev if f == feature and k == kind), None)
            row = rows[group(os.path.basename(p))][label]
            row[0] += idx is not None and idx >= FAULT_START
            row[1] += idx is not None and idx < FAULT_START
            row[2] += any(f != feature and k == kind for _, f, k in ev)
            row[3] += 1
    return rows


CONFIGS = [("A", "A", None, False), ("B1.3", "B", 1.3, False),
           ("B1.15", "B", 1.15, False), ("C", "A", None, True)]


def counts(table):
    return {g: {l: tuple(v) for l, v in d.items()} for g, d in table.items()}


class AgainstAnalyzeNoiseTest(unittest.TestCase):
    """Implementação independente: analyze_noise monta o SubsetDetector direto."""

    def test_every_event_matches_on_every_noise_file(self):
        for p in files("results/noise/np*-*.jsonl") + files("results/noise/ncontrol-*.jsonl"):
            ld = load_samples(p)
            samples = ld.samples[1:]
            for feature in ("heavy-reports", "dashboard"):
                for label, rule, ratio in (("A", "A", 1.3), ("B1.3", "B", 1.3), ("B1.15", "B", 1.15)):
                    ref = with_ratio(ratio, lambda: agent_events(samples, feature, rule))
                    r = replay(ld.samples, "x", rule, ratio, 1)
                    got = [(i, k) for i, f, k in r.events if f == feature]
                    self.assertEqual(got, ref, (os.path.basename(p), feature, label))
                ref_c = with_ratio(1.3, lambda: agent_events(samples, feature, "C"))
                r = replay(ld.samples, "x", "A", 1.3, 1)
                got_c = [(i, k.replace("c_", "")) for i, f, k in r.watch if f == feature]
                self.assertEqual(got_c, ref_c, (os.path.basename(p), feature, "C"))


class NoiseResumoTest(unittest.TestCase):
    def test_noise_resumo_counts(self):
        t = counts(hit_table("results/noise/np*-*.jsonl",
                             lambda n: re.match(r"np([\d.]+)", n).group(1), CONFIGS))
        # n=10 por fração. results/noise/RESUMO.md: A 0/0, B 1,3x 7/1, B' 10/10, C 0/0; sem falso nem quebra de isolamento
        self.assertEqual(t["0.2"], {"A": (0, 0, 0, 10), "B1.3": (7, 0, 0, 10), "B1.15": (10, 0, 0, 10), "C": (0, 0, 0, 10)})
        self.assertEqual(t["0.1"], {"A": (0, 0, 0, 10), "B1.3": (1, 0, 0, 10), "B1.15": (10, 0, 0, 10), "C": (0, 0, 0, 10)})


class PartialResumoTest(unittest.TestCase):
    def test_partial_resumo_counts(self):
        t = counts(hit_table("results/partial/*.jsonl",
                             lambda n: re.sub(r"\d*-[ab]\.jsonl$", "", n), CONFIGS))
        # results/partial/RESUMO.md: B 6/6 em 20% e 10%, 3/6 em 5%; A e C 0; dashboard cego
        for frac, b in (("hp0.2r", 6), ("hp0.1r", 6), ("hp0.05r", 3)):
            self.assertEqual(t[frac]["A"], (0, 0, 0, 6), frac)
            self.assertEqual(t[frac]["B1.15"], (b, 0, 0, 6), frac)
            self.assertEqual(t[frac]["C"], (0, 0, 0, 6), frac)
        for label in ("A", "B1.15", "C"):
            self.assertEqual(t["dp"][label], (0, 0, 0, 6), label)  # nenhuma regra vê dashboard +0,5 s


class Step3ResumoTest(unittest.TestCase):
    def test_step3_resumo_counts(self):
        agg = defaultdict(lambda: defaultdict(int))
        total = defaultdict(int)
        for p in files("results/step3/*.jsonl"):
            kind = re.match(r"(ctrl|mix|reg)", os.path.basename(p)).group(1)
            ld = load_samples(p)
            total[kind] += 1
            for label, rule in (("A", "A"), ("B", "B")):
                r = replay(ld.samples, "x", rule, None, 1)
                self.assertEqual(r.gaps, [])
                agg[kind][label] += any(k == "detected" for _, _, k in r.events)
            r = replay(ld.samples, "x", "A", None, 1)
            agg[kind]["C"] += any(k == "c_detected" for _, _, k in r.watch)
        # results/step3/RESUMO.md, por feature: controle 0/2; mistura 0/10; regressão A 0, B 10, C 10
        self.assertEqual((total["ctrl"], total["mix"], total["reg"]), (2, 10, 10))
        self.assertEqual(dict(agg["ctrl"]), {"A": 0, "B": 0, "C": 0})
        self.assertEqual(dict(agg["mix"]), {"A": 0, "B": 0, "C": 0})
        self.assertEqual(dict(agg["reg"]), {"A": 0, "B": 10, "C": 10})


class ControlsTest(unittest.TestCase):
    def test_controls_have_zero_alarms_in_every_rule(self):
        for pat in ("results/control/control-*.jsonl", "results/noise/ncontrol-*.jsonl"):
            for p in files(pat):
                ld = load_samples(p)
                for rule in ("A", "B"):
                    r = replay(ld.samples, "x", rule, None, 1)
                    self.assertEqual([e for e in r.events if e[2] == "detected"], [], (p, rule))
                self.assertEqual(r.watch, [], p)

    def test_30h_control_counts_match_the_readme(self):
        # results/control-72h/README.md: 2367 linhas, 1800 janelas, 564 duplicatas, 3 erros, 5 buracos
        for p in files("results/control-72h/control-*.jsonl"):
            ld = load_samples(p)
            # 2367 linhas = 1800 janelas + 564 duplicatas + 3 erros de coleta (README e contagem por minuto)
            self.assertEqual((ld.lines, len(ld.samples), ld.duplicates, ld.errors), (2367, 1800, 564, 3), p)
            self.assertEqual(ld.lines, len(ld.samples) + ld.duplicates + ld.errors, p)
            r = replay(ld.samples, "x", "B", None, 1)
            self.assertEqual(len(r.gaps), 5, p)
            self.assertEqual([e for e in r.events if e[2] == "detected"], [], p)


if __name__ == "__main__":
    unittest.main()
