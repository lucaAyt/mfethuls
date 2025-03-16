import unittest
from src.mfethuls import parse as pa


class MyTestCase(unittest.TestCase):
    def test_something(self):
        kw = 'uv'
        print(pa.path_constructor(kw))
        df = pa.get_data(pa.path_constructor(kw), kw)
        print(df)


if __name__ == '__main__':
    unittest.main()
