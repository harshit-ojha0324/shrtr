from app.services.codegen import ALPHABET, CODE_LENGTH, generate_code, is_valid_alias


def test_code_length_and_charset():
    for _ in range(200):
        code = generate_code()
        assert len(code) == CODE_LENGTH
        assert all(c in ALPHABET for c in code)


def test_alphabet_has_no_lookalikes():
    assert not set("0Oo1lI") & set(ALPHABET)


def test_codes_are_not_obviously_repeating():
    codes = {generate_code() for _ in range(2000)}
    assert len(codes) == 2000  # collision in 2000 draws from 56^8 would be astonishing


def test_alias_rules():
    assert is_valid_alias("my-link")
    assert is_valid_alias("abc")
    assert is_valid_alias("x" * 32)
    assert not is_valid_alias("ab")            # too short
    assert not is_valid_alias("x" * 33)        # too long (links.short_code is varchar(32))
    assert not is_valid_alias("has space")
    assert not is_valid_alias("abcd+")         # '+' is the preview suffix
    assert not is_valid_alias("abcd\n")        # re.match + $ would accept this
    assert not is_valid_alias("api")           # reserved
    assert not is_valid_alias("Metrics")       # reserved, case-insensitive
