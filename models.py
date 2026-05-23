from dataclasses import dataclass
import time


@dataclass
class User:
    username: str
    password_hash: str
    is_admin: bool
    failed_attempts: int = 0
    locked_until: int = 0
    need_change_password: bool = False

    def is_locked(self):
        return self.locked_until > int(time.time())

    def remaining_lockout_minutes(self):
        if not self.is_locked:
            return 0
        return int((self.locked_until - int(time.time())) / 60)
