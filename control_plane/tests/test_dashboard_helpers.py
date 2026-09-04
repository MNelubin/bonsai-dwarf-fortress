from bonsai_control.main import failure_class


def test_failure_class_exposes_actionable_categories():
    assert failure_class("empty old is only valid for a new file") == "patch_protocol"
    assert failure_class("model request timed out after deadline") == "timeout"
    assert failure_class("mypy validation failed") == "validation"
    assert failure_class(None) is None
