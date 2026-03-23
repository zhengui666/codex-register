from src.services.base import (
    EmailProviderBackoffState,
    OTPTimeoutEmailServiceError,
    RateLimitedEmailServiceError,
    apply_adaptive_backoff,
    calculate_adaptive_backoff_delay,
)


def test_calculate_adaptive_backoff_delay_uses_failure_count_progression():
    assert calculate_adaptive_backoff_delay(0) == 30
    assert calculate_adaptive_backoff_delay(1) == 30
    assert calculate_adaptive_backoff_delay(2) == 60
    assert calculate_adaptive_backoff_delay(3) == 120


def test_apply_adaptive_backoff_tracks_timeout_failures_to_one_hour():
    state = EmailProviderBackoffState()

    first = apply_adaptive_backoff(
        state,
        OTPTimeoutEmailServiceError("等待验证码超时", error_code="OTP_TIMEOUT_SECONDARY"),
        now=1000.0,
    )
    second = apply_adaptive_backoff(
        first,
        OTPTimeoutEmailServiceError("等待验证码超时", error_code="OTP_TIMEOUT_SECONDARY"),
        now=1031.0,
    )
    third = apply_adaptive_backoff(
        second,
        OTPTimeoutEmailServiceError("等待验证码超时", error_code="OTP_TIMEOUT_SECONDARY"),
        now=1092.0,
    )

    assert first.failures == 1
    assert first.delay_seconds == 30
    assert first.opened_until == 1030.0

    assert second.failures == 2
    assert second.delay_seconds == 60
    assert second.opened_until == 1091.0

    assert third.failures == 3
    assert third.delay_seconds == 3600
    assert third.opened_until == 4692.0


def test_apply_adaptive_backoff_keeps_normal_rate_limit_on_exponential_curve():
    state = EmailProviderBackoffState(failures=2, delay_seconds=60, opened_until=1060.0)

    next_state = apply_adaptive_backoff(
        state,
        RateLimitedEmailServiceError("请求失败: 429", retry_after=7),
        now=1100.0,
    )

    assert next_state.failures == 3
    assert next_state.delay_seconds == 120
    assert next_state.opened_until == 1220.0
    assert next_state.retry_after == 7
