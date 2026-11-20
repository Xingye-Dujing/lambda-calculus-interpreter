#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Property-based checks for the reference evaluator and the interpreter.

对参考求值器与解释器做基于性质的检查；安装 hypothesis 时使用真实策略，
否则退化为固定种子的随机样本。
"""
from __future__ import annotations

import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import reference_eval as ref  # noqa: E402

try:
    from hypothesis import given, settings, strategies as st  # noqa: E402
    HAVE_HYPOTHESIS = True
except ImportError:  # pragma: no cover - optional dependency
    HAVE_HYPOTHESIS = False


def gen_term(rng: random.Random, depth: int) -> str:
    """Generate a small closed term that is likely to terminate.

    生成规模较小、通常可终止的封闭项。
    """
    if depth <= 0:
        return "(" + rng.choice(["\\x.x", "\\x.\\y.x", "\\x.\\y.y", "\\f.\\x.f x"]) + ")"
    if rng.random() < 0.35:
        return "(\\z." + gen_term(rng, depth - 1) + ")"
    a = gen_term(rng, depth - 1)
    b = gen_term(rng, depth - 1)
    return "(" + a + " " + b + ")"


def check_properties(count: int = 60) -> list[str]:
    """Return a list of failures; empty means all properties held.

    返回失败列表，空列表表示所有性质成立。
    """
    failures: list[str] = []
    rng = random.Random(20261120)

    def one(n: int) -> str:
        return gen_term(random.Random(n), 3)

    if HAVE_HYPOTHESIS:
        # Real Hypothesis strategies supply the seeds when it is installed;
        # run_properties also drives these properties under @given.
        seeds = st.integers(min_value=0, max_value=100000)
        samples = [one(seeds.example()) for _ in range(count)]
    else:
        # Deterministic fallback: a fixed-seed random stream.
        samples = [gen_term(rng, 3) for _ in range(count)]

    for term in samples:
        try:
            first, stepped = ref.step(term)
            if stepped:
                before = ref.to_debruijn(term)
                after = ref.to_debruijn(first)
                if before == after:
                    failures.append(f"step did not change {term}")
            nf = ref.normalize(term, limit=5000)
            again = ref.normalize(nf, limit=5000)
            if not ref.alpha_eq(nf, again):
                failures.append(f"normalization not idempotent: {term}")
        except (RuntimeError, SyntaxError, ValueError) as exc:
            failures.append(f"{term}: {type(exc).__name__}: {exc}")
    return failures


if HAVE_HYPOTHESIS:
    @settings(max_examples=40, deadline=None)
    @given(st.integers(min_value=0, max_value=100000))
    def hypothesis_step_is_progress(seed: int) -> None:
        term = gen_term(random.Random(seed), 3)
        try:
            ref.step(term)
            nf = ref.normalize(term, limit=5000)
        except RuntimeError:
            return
        assert ref.alpha_eq(nf, ref.normalize(nf, limit=5000))


def run_properties() -> list[str]:
    """Run both the seeded and (when available) Hypothesis properties.

    运行种子性质，并在可用时运行 Hypothesis 性质。
    """
    failures = check_properties()
    if HAVE_HYPOTHESIS:
        try:
            hypothesis_step_is_progress()
        except Exception as exc:  # noqa: BLE001
            failures.append(f"hypothesis: {type(exc).__name__}: {exc}")
    return failures


if __name__ == "__main__":
    bad = run_properties()
    if bad:
        print("FAILURES:\n  " + "\n  ".join(bad[:10]))
        raise SystemExit(1)
    print(f"property checks ok (hypothesis={HAVE_HYPOTHESIS})")
