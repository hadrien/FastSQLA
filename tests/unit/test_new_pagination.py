import inspect
from collections.abc import Callable
from typing import cast

from pytest import mark, raises, warns


def _default_limit(dependency: Callable[..., object]) -> int:
    parameter = inspect.signature(dependency).parameters["limit"]
    return cast(int, parameter.default.default)


def test_it_uses_default_page_size():
    from fastsqla import new_pagination

    dependency = new_pagination(default_page_size=5)

    assert _default_limit(dependency) == 5, (
        "Configured page size must be the default limit"
    )


def test_it_preserves_positional_default_page_size():
    from fastsqla import new_pagination

    dependency = new_pagination(5)

    assert _default_limit(dependency) == 5, (
        "First positional argument must keep its meaning"
    )


def test_it_accepts_deprecated_min_page_size():
    from fastsqla import new_pagination

    with warns(DeprecationWarning, match="use default_page_size instead") as captured:
        dependency = new_pagination(min_page_size=5)

    assert captured[0].filename == __file__, "Warning must identify the caller"
    assert _default_limit(dependency) == 5, (
        "Deprecated name must preserve configured default"
    )


@mark.parametrize(
    ("args", "kwargs"),
    [
        ((5,), {"min_page_size": 5}),
        ((), {"default_page_size": 5, "min_page_size": 5}),
    ],
)
def test_it_rejects_both_page_size_names(args, kwargs):
    from fastsqla import new_pagination

    with raises(
        TypeError, match="cannot receive both default_page_size and min_page_size"
    ):
        new_pagination(*args, **kwargs)


@mark.parametrize(
    ("default_page_size", "max_page_size", "message"),
    [
        (0, 100, "default_page_size must be between 1 and max_page_size"),
        (101, 100, "default_page_size must be between 1 and max_page_size"),
        (10, 0, "max_page_size must be at least 1"),
    ],
)
def test_it_rejects_invalid_page_size_configuration(
    default_page_size, max_page_size, message
):
    from fastsqla import new_pagination

    with raises(ValueError, match=message):
        new_pagination(default_page_size=default_page_size, max_page_size=max_page_size)
