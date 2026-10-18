Based on the case table from the manual test-stand verification, write integration tests covering those scenarios that are not yet covered. First check which integration tests already cover this functionality for the task.
Requirements:
- Follow integration-testing best practices: test component interaction through real (or test) DB/API, not by mocking internal logic; clearly separate arrange/act/assert; use short, descriptive test names reflecting scenario and expected result.
- Cover happy path, negative and corner cases from the table — each case maps to its own test or its own parameter in a parametrized test.
- Reuse existing fixtures and helpers from unit and other integration tests; do not duplicate them.
- Use pytest parametrization for same-shape scenarios (e.g. variants of invalid input) instead of near-duplicate functions.
- Assert the actual DB state after the operation only when the table case calls for it.
- Tests must be isolated, idempotent and order-independent; each test sets up and cleans up its own data.
- Group new tests into test classes (e.g. `class TestSomeFeature:`) per scenario/feature, not top-level module functions.
After writing, run the tests and make sure they pass.

IMPORTANT: all output for the user must be in Russian (answers, reports, questions, plans, summaries and any generated texts), even though this prompt is in English.
