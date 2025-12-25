from src.core.domain.validation import ValidationResult


def test_validation_result_success():
    res = ValidationResult.success()
    assert res.is_valid is True
    assert not res.errors
    assert bool(res) is True


def test_validation_result_failure():
    res = ValidationResult.failure("error 1")
    assert res.is_valid is False
    assert res.errors == ["error 1"]
    assert bool(res) is False

    res2 = ValidationResult.failure(["e1", "e2"])
    assert res2.errors == ["e1", "e2"]
