# qa-calc

Учебный калькулятор для ручного E2E-тестирования трекера.

- `calc.py` — функции `add`, `subtract`, `multiply`.
- `test_calc.py` — тесты на `unittest`: `python3 -m unittest -v`.

Задача тестового прогона — добавить `divide(left, right)`: деление,
а при `right == 0` — `ZeroDivisionError` с понятным сообщением, и тесты к ней.
