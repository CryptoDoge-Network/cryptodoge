import unittest

from cryprotdoge.util.setproctitle import setproctitle


class TestSetProcTitle(unittest.TestCase):
    def test_does_not_crash(self):
        setproctitle("cryprotdoge test title")
