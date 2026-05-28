class AuthError(Exception):
    pass


class UserNotFound(AuthError):
    pass


class InvalidPassword(AuthError):
    pass


class AccountLocked(AuthError):
    pass


class RateLimitExceeded(AuthError):
    pass


class PermissionDenied(AuthError):
    pass


class PasswordValidation(AuthError):
    pass
