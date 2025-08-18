from src.command_processor import parse_arguments


def test_parse_arguments_empty():
    assert parse_arguments("") == {}
    assert parse_arguments("   ") == {}


def test_parse_arguments_simple_key_value():
    assert parse_arguments("key=value") == {"key": "value"}
    assert parse_arguments("  key  =  value  ") == {"key": "value"}


def test_parse_arguments_multiple_key_values():
    expected = {"key1": "value1", "key2": "value2"}
    assert parse_arguments("key1=value1,key2=value2") == expected
    assert parse_arguments("  key1 = value1 ,  key2 = value2  ") == expected


def test_parse_arguments_boolean_true():
    assert parse_arguments("flag") == {"flag": True}
    assert parse_arguments("  flag  ") == {"flag": True}
    assert parse_arguments("flag1,key=value,flag2") == {
        "flag1": True,
        "key": "value",
        "flag2": True,
    }


def test_parse_arguments_mixed_values():
    # E501: Linelength
    expected = {"str_arg": "hello world", "bool_arg": True, "num_arg": "123"}
    assert parse_arguments('str_arg="hello world", bool_arg, num_arg=123') == expected


def test_parse_arguments_quotes_stripping():
    assert parse_arguments('key="value"') == {"key": "value"}
    assert parse_arguments("key='value'") == {"key": "value"}
    # E501: Linelength
    assert parse_arguments('key=" value with spaces "') == {
        "key": " value with spaces "
    }
