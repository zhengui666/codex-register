from types import SimpleNamespace

from src.core.register import RegistrationEngine


def test_extract_callback_url_from_escaped_script_text():
    engine = RegistrationEngine.__new__(RegistrationEngine)
    text = (
        '<script>window.__STATE__={"callbackUrl":"https:\\/\\/chatgpt.com\\/api/auth/'
        'callback/openai?code=abc123\\u0026state=xyz456"};</script>'
    )

    callback_url = engine._extract_callback_url_from_text(text)

    assert callback_url == "https://chatgpt.com/api/auth/callback/openai?code=abc123&state=xyz456"


def test_submit_consent_form_supports_method_before_action():
    engine = RegistrationEngine.__new__(RegistrationEngine)
    calls = []

    def fake_post(url, data, allow_redirects, timeout):
        calls.append((url, data, allow_redirects, timeout))
        return SimpleNamespace(
            headers={"Location": "/api/auth/callback/openai?code=formcode&state=formstate"},
            text="",
        )

    engine.session = SimpleNamespace(post=fake_post, get=None)

    next_url = engine._submit_consent_form(
        "https://auth.openai.com/sign-in-with-chatgpt/codex/consent",
        '<form method="post" action="/consent/submit"><input name="state" value="abc"></form>',
    )

    assert next_url == "https://auth.openai.com/api/auth/callback/openai?code=formcode&state=formstate"
    assert calls == [
        ("https://auth.openai.com/consent/submit", {"state": "abc"}, False, 15),
    ]


def test_submit_consent_form_falls_back_to_embedded_callback_without_form():
    engine = RegistrationEngine.__new__(RegistrationEngine)

    next_url = engine._submit_consent_form(
        "https://auth.openai.com/sign-in-with-chatgpt/codex/consent",
        (
            '<script id="__NEXT_DATA__" type="application/json">'
            '{"continueUrl":"https%3A%2F%2Fchatgpt.com%2Fapi%2Fauth%2Fcallback%2Fopenai%3Fcode%3Dspa123%26state%3Dspa456"}'
            "</script>"
        ),
    )

    assert next_url == "https://chatgpt.com/api/auth/callback/openai?code=spa123&state=spa456"
