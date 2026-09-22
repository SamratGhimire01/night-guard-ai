import smtplib


def test_suite_never_opens_a_real_smtp_connection():
    """tests/conftest.py must keep faking smtplib.SMTP — real sends spent the platform Gmail's daily quota (Phase 19)."""
    with smtplib.SMTP("smtp.gmail.com", 587, timeout=1) as smtp:
        assert smtp.send_message(object()) == {}
