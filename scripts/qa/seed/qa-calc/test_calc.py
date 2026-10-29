import unittest

from calc import add, multiply, subtract


class TestCalc(unittest.TestCase):
    def test_add(self) -> None:
        self.assertEqual(add(2, 3), 5)

    def test_subtract(self) -> None:
        self.assertEqual(subtract(5, 3), 2)

    def test_multiply(self) -> None:
        self.assertEqual(multiply(4, 3), 12)


if __name__ == "__main__":
    unittest.main()
