import pytest

from server.stt import is_meaningful


@pytest.mark.parametrize(
    "text,ok",
    [
        ("", False),
        ("a", False),
        ("Altyazı M.K.", False),
        ("İzlediğiniz için teşekkürler.", False),
        ("Abone olmayı unutmayın!", False),
        ("dosyaları listele", True),
        ("dur", True),
    ],
)
def test_is_meaningful(text, ok):
    assert is_meaningful(text) is ok
