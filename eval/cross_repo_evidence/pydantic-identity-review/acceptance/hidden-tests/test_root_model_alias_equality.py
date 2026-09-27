from typing_extensions import TypeAliasType
from pydantic import RootModel


SomeStr = TypeAliasType('SomeStr', str)


def test_equivalent_aliases_compare_equal():
    assert RootModel[str]('a') == RootModel[SomeStr]('a')


def test_distinct_parametrizations_remain_unequal():
    assert RootModel[int](1) != RootModel[float](1)
