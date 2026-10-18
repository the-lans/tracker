Check whether the written code follows the rules below. You are in Agent mode: after listing the needed fixes, apply them immediately!
Follow these rules when writing code:

=== Backend ===
1. Follow professional, state-of-the-art development and testing practices.
2. Put imports at the top of the module, not inside functions, unless there are circular imports.
3. In SQL queries do not use table aliases — only real table names.
4. Type variables and functions. In new code add types wherever possible and reasonable.
5. Decompose code into small functions/methods (Single Responsibility Principle).
6. No magic numbers/strings — move them to constants or config. Allowed only in tests.
7. Avoid `except Exception:` unless necessary; catch specific exception types. If specific types cannot be determined, Exception is acceptable.
8. Handle transactions: either explicit transaction blocks or a consistent approach (unit of work).
9. Do not optimize without measurement. Profile and find the bottleneck first, then optimize.
10. Use pytest and fixtures for environment and test data setup. Always check which fixtures already exist.
11. Cover happy path, main negative scenarios and edge cases with tests.
12. If the API is affected, generate and maintain the spec. When an endpoint signature changes, update the spec in the same commit.
13. Validate input data: types, ranges, formats (especially in APIs).
14. Follow project structure: separate presentation (API), business logic, data access and utilities. Move shared functionality into a library.
15. Keep a consistent code style via `pre-commit run --all-files`, i.e. `ruff check --fix` for linting and `mypy` for type checking.
16. Important: where tests check several same-shape scenarios or similar logic, parametrize them.
17. Test names must be short and meaningful. No overly long function names in general.
18. Group new tests into test classes (e.g. `class TestSomeFeature:`) per scenario/feature, not top-level module functions.
19. If a function/method has more than five arguments, positional arguments at call sites are forbidden. Define such functions so all "real" arguments are keyword-only, and pass arguments by name at every call site.
20. The models file/folder contains only models; DB access functions go to a separate layer — db.
21. Use trailing commas where they improve readability: many arguments/elements, long or complex elements, already multi-line constructs. No trailing comma in short one-line constructs.
22. Write only meaningful comments.
23. In SQL migrations use IF NOT EXISTS / IF EXISTS for CREATE, ALTER, DROP so a repeated run doesn't crash the service.
24. Long docstrings/comments in """ """ must have the text on its own line, not on the same line as the quotes.
   Wrong: """Long text"""
   Right:
   """
   Long text
   """

=== Frontend ===
25. Follow the ESLint and Prettier config already in the project. Do not generate code that violates these rules. If there is no config, create a basic eslint.config.js with rules for the framework in use.
26. Use TypeScript everywhere. The `any` type is forbidden without an explicit justification in a comment. Describe interfaces and types for complex data structures in separate *.types.ts files.
27. Keep components small and focused (Single Responsibility). If a component grows, decompose it into child components or move logic into hooks / composables / utilities.
28. Do not access the DOM directly via document.querySelector and the like where the framework solves it (React ref, Vue ref, etc.).
29. If the project has i18n, don't hardcode strings around it. If there is no i18n but localization is planned, move UI text into a separate dictionary object.
30. Always wrap async operations (fetch, axios, etc.) in error handling. No "bare" promises without .catch() or try/catch.
31. Use one state-management approach across the project (e.g. only React Query + Context, or only Pinia). Do not mix strategies without justification.
32. Cover components with tests via Vitest + Testing Library. Test behavior (what the user sees and does), not implementation details (internal methods, state).
33. Use dynamic imports (import()) for heavy dependencies and routes. Do not add a library to the bundle for one function — find a tree-shaking-friendly alternative or write the utility yourself.

IMPORTANT: all output for the user must be in Russian (answers, reports, questions, plans, summaries and any generated texts), even though this prompt is in English.
