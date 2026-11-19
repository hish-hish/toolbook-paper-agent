"""应用内登录门：凭据来自环境变量，常量时间比较，纯函数离线可测。

云部署设 TOOLBOOK_AUTH_USER / TOOLBOOK_AUTH_PASS 即开启登录门（所有人凭同一账号密码访问）；
本地开发不设这两个变量则门关闭，直接可用。凭据绝不硬编码、绝不入库。
"""
import hmac
import os


def auth_enabled() -> bool:
    """登录门是否开启：用户名与密码环境变量都非空才开启（半配置视为关闭）。"""
    return bool(os.environ.get("TOOLBOOK_AUTH_USER", "").strip()
                and os.environ.get("TOOLBOOK_AUTH_PASS", "").strip())


def verify_login(user: str, password: str) -> bool:
    """校验登录凭据：未开启或任一不匹配返回 False；用常量时间比较防时序侧信道。"""
    if not auth_enabled():
        return False
    expect_user = os.environ.get("TOOLBOOK_AUTH_USER", "")
    expect_pass = os.environ.get("TOOLBOOK_AUTH_PASS", "")
    if not user or not password:
        return False
    # 按字节比较，兼容中文密码；compare_digest 常量时间，避免逐字符短路泄露信息
    ok_user = hmac.compare_digest(user.encode("utf-8"), expect_user.encode("utf-8"))
    ok_pass = hmac.compare_digest(password.encode("utf-8"), expect_pass.encode("utf-8"))
    return ok_user and ok_pass