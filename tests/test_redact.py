"""Tests for secret and PII redaction."""

from ard.adapters.forge import _redact


class TestAPIKeys:
    def test_anthropic_key(self):
        assert "[REDACTED]" in _redact("key=sk-ant-api03-FAKEFAKEFAKEFAKEFAKE")

    def test_openai_key(self):
        assert "[REDACTED]" in _redact("key=sk-proj-FAKEFAKEFAKEFAKEFAKEFAKE")

    def test_supabase_token(self):
        assert "[REDACTED]" in _redact("token=sbp_00000000000000000000000000000000deadbeef")

    def test_github_pat(self):
        assert "[REDACTED]" in _redact("ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZab")

    def test_github_oauth(self):
        assert "[REDACTED]" in _redact("gho_ABCDEFGHIJKLMNOPQRSTUVWXYZab")

    def test_slack_bot_token(self):
        assert "[REDACTED]" in _redact("xoxb-123-456-abcdefgh")

    def test_slack_user_token(self):
        assert "[REDACTED]" in _redact("xoxp-123-456-abcdefgh")

    def test_jwt(self):
        jwt = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJmYWtlIjoiZmFrZWZha2VmYWtl.FAKEFAKEFAKEFAKEFAKEFAKEFAKE"
        assert "[REDACTED]" in _redact(jwt)
        assert "eyJ" not in _redact(jwt)


class TestKeyValueSecrets:
    def test_password_equals(self):
        assert "[REDACTED]" in _redact("password=MySecret123!")

    def test_api_key_colon(self):
        assert "[REDACTED]" in _redact("api_key: sk-something")

    def test_access_token(self):
        assert "[REDACTED]" in _redact("access_token=abc123def456")

    def test_service_role_key(self):
        assert "[REDACTED]" in _redact("service_role_key=eyJhbGci...")

    def test_secret_mixed_case(self):
        assert "[REDACTED]" in _redact("SECRET=hunter2")


class TestPII:
    def test_email(self):
        result = _redact("contact user@example.com for details")
        assert "[email]" in result
        assert "user@example.com" not in result

    def test_phone(self):
        result = _redact("call 555-123-4567 for help")
        assert "[phone]" in result
        assert "555-123-4567" not in result

    def test_ip_address(self):
        result = _redact("connected to 192.168.1.100")
        assert "[ip]" in result
        assert "192.168.1.100" not in result

    def test_macos_user_path(self):
        result = _redact("/Users/anisha/Documents/project")
        assert "/Users/dev" in result
        assert "anisha" not in result

    def test_linux_user_path(self):
        result = _redact("/home/anisha/.config/app")
        assert "/home/dev" in result
        assert "anisha" not in result

    def test_uuid(self):
        result = _redact("session 6673c706-f625-43ad-a23e-71c9a0a7e144")
        assert "[uuid]" in result
        assert "6673c706" not in result

    def test_github_username_in_url(self):
        result = _redact("https://github.com/anisha-agarwal/repo")
        assert "github.com/user/" in result
        assert "anisha-agarwal" not in result


class TestPreservesNonSecrets:
    def test_normal_text(self):
        text = "Let me read the component structure and fix the bug"
        assert _redact(text) == text

    def test_code_snippet(self):
        text = "const result = await fetch('/api/data');"
        assert _redact(text) == text

    def test_file_paths_without_user(self):
        text = "src/components/rewards.tsx"
        assert _redact(text) == text

    def test_short_tokens_not_matched(self):
        text = "sk-short"
        assert _redact(text) == text
