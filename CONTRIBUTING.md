# Contributing

Start with the user outcome, a reproducible example, and acceptance checks. Keep packet approval, run limits, worker isolation, failure records, and human merge authority intact.

Open an issue or draft PR with expected and actual behavior, source revision, runtime, a minimal reproduction, and redacted check results. Never include account caches, private tickets, customer data, or credentials. Native integration checks require your own documented host prerequisites and account; simulations must be labeled.

For source changes, run `python3 scripts/validate-poc.py` and `bash scripts/check-dead-code.sh` (the latter uses pinned Vulture 2.16 through `uvx`). Validation covers controller regression tests, Python compilation, and the preserved synthetic demo, with a receipt under `.evidence`. A dirty checkout is labeled blocked for exact-commit validation; commit the reviewed change and rerun before publication. Add a focused regression test for changed behavior. The maintainer decides merges and releases. This experimental alpha has no production-support commitment.
