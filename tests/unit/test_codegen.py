from app.services.codegen import BASE62, CODE_LENGTH, generate_code, is_valid_alias


def test_code_length_and_charset():
    for _ in range(200):
        code = generate_code()
        assert len(code) == CODE_LENGTH
        assert all(c in BASE62 for c in code)


def test_codes_are_not_obviously_repeating():
    codes = {generate_code() for _ in range(2000)}
    assert len(codes) == 2000  # collision in 2000 draws from 62^7 would be astonishing


def test_alias_rules():
    assert is_valid_alias("my-link")
    assert is_valid_alias("abc_123")
    assert not is_valid_alias("ab")            # too short
    assert not is_valid_alias("x" * 13)        # too long
    assert not is_valid_alias("has space")
    assert not is_valid_alias("api")           # reserved
    assert not is_valid_alias("metrics")       # reserved
