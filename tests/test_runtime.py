import sys


def test_supported_python_runtime() -> None:
    assert (3, 11) <= sys.version_info[:2] < (3, 14)

