# Unit test (no DB): the per-IP failure cap of sign-in, over the DB-counted window.
import pytest

from app.application.auth_service import IP_WINDOW_MINUTES, MAX_IP_FAILURES, AuthError, AuthService
from app.application.errors import TooManyRequests


class FakeRepo:
    def __init__(self, failures):
        self.failures, self.asked = failures, []

    def recent_ip_failures(self, ip, minutes):
        self.asked.append((ip, minutes))
        return self.failures.get(ip, 0)

    def find_user_by_email(self, email):
        return None  # unknown user: a normal 401

    def audit(self, *args):
        pass

    def commit(self):
        pass


def test_ip_failure_cap():
    repo = FakeRepo({"203.0.113.9": MAX_IP_FAILURES, "203.0.113.10": MAX_IP_FAILURES - 1})
    with pytest.raises(TooManyRequests):
        AuthService(repo).login("a@b.mx", "x", "203.0.113.9", None)
    with pytest.raises(AuthError):  # under the cap: the usual invalid-credentials answer
        AuthService(repo).login("a@b.mx", "x", "203.0.113.10", None)
    assert repo.asked[0] == ("203.0.113.9", IP_WINDOW_MINUTES)
