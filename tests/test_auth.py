"""登录门离线单测：开关判定与凭据校验（常量时间比较），不依赖 Streamlit。"""
import toolbook.auth as auth


def test_auth_disabled_when_unset(monkeypatch):
    # 本地开发未设凭据：登录门关闭，所有人可直接访问
    monkeypatch.delenv("TOOLBOOK_AUTH_USER", raising=False)
    monkeypatch.delenv("TOOLBOOK_AUTH_PASS", raising=False)
    assert auth.auth_enabled() is False


def test_auth_enabled_when_both_set(monkeypatch):
    # 用户名与密码都配置：登录门开启
    monkeypatch.setenv("TOOLBOOK_AUTH_USER", "hish")
    monkeypatch.setenv("TOOLBOOK_AUTH_PASS", "secret")
    assert auth.auth_enabled() is True


def test_auth_disabled_when_only_user(monkeypatch):
    # 只配用户名缺密码：视为未启用（避免半配置误锁/误放）
    monkeypatch.setenv("TOOLBOOK_AUTH_USER", "hish")
    monkeypatch.delenv("TOOLBOOK_AUTH_PASS", raising=False)
    assert auth.auth_enabled() is False


def test_verify_login_correct(monkeypatch):
    # 凭据完全匹配：放行
    monkeypatch.setenv("TOOLBOOK_AUTH_USER", "hish")
    monkeypatch.setenv("TOOLBOOK_AUTH_PASS", "secret")
    assert auth.verify_login("hish", "secret") is True


def test_verify_login_wrong_password(monkeypatch):
    # 密码错：拒绝
    monkeypatch.setenv("TOOLBOOK_AUTH_USER", "hish")
    monkeypatch.setenv("TOOLBOOK_AUTH_PASS", "secret")
    assert auth.verify_login("hish", "wrong") is False


def test_verify_login_wrong_user(monkeypatch):
    # 用户名错：拒绝
    monkeypatch.setenv("TOOLBOOK_AUTH_USER", "hish")
    monkeypatch.setenv("TOOLBOOK_AUTH_PASS", "secret")
    assert auth.verify_login("other", "secret") is False


def test_verify_login_disabled(monkeypatch):
    # 未启用时任何凭据都不放行（门关闭由 UI 跳过，校验本身保守返回 False）
    monkeypatch.delenv("TOOLBOOK_AUTH_USER", raising=False)
    monkeypatch.delenv("TOOLBOOK_AUTH_PASS", raising=False)
    assert auth.verify_login("hish", "secret") is False


def test_verify_login_empty_input(monkeypatch):
    # 空用户名/空密码：拒绝（即便服务端凭据也为空也不放行）
    monkeypatch.setenv("TOOLBOOK_AUTH_USER", "hish")
    monkeypatch.setenv("TOOLBOOK_AUTH_PASS", "secret")
    assert auth.verify_login("", "") is False


def test_verify_login_unicode_password(monkeypatch):
    # 含中文密码：常量时间比较须按字节处理，不抛 TypeError
    monkeypatch.setenv("TOOLBOOK_AUTH_USER", "hish")
    monkeypatch.setenv("TOOLBOOK_AUTH_PASS", "密码123")
    assert auth.verify_login("hish", "密码123") is True
    assert auth.verify_login("hish", "密码124") is False