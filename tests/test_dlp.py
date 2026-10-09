from agentgate.dlp import redact


def test_nested_redaction_and_nonmatching_data():
    value = {
        "nested": [{"mail": "person@example.test", "ssn": "123-45-6789"}],
        "safe": 123,
        "secret": "sk-abcdefghijklmnopqrstuvwxyz",
        "text": "support escalation",
    }
    clean, counts = redact(value)
    assert counts == {"email": 1, "ssn": 1, "api_key": 1}
    assert clean["safe"] == 123 and clean["text"] == "support escalation"
    assert clean["nested"][0]["mail"] == "[REDACTED:email]"


def test_redaction_checks_dictionary_keys():
    clean, counts = redact({"user@example.test": "safe"})
    assert clean == {"[REDACTED:email]": "safe"}
    assert counts == {"email": 1}
