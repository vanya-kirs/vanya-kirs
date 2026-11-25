from app.parser.exceptions import BannedError


def test_banned_error_is_exception():
    err = BannedError("banned")
    assert isinstance(err, Exception)
    assert str(err) == "banned"
