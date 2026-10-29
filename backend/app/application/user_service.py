from app.application.errors import Conflict, Forbidden, Invalid, NotFound
from app.application.ports.user_repository import UserRepository
from app.application.security import hash_password, password_problems, temporary_password, verify_password


class UserService:
    def __init__(self, repo: UserRepository):
        self.repo = repo

    # --- admin ---

    def list(self, q, status, branch_id, page, page_size):
        items, total = self.repo.search(q.strip(), status, branch_id, page_size, (page - 1) * page_size)
        return {"items": items, "total": total, "page": page, "page_size": page_size}

    def get(self, user_id):
        user = self.repo.get(user_id)
        if user is None:
            raise NotFound("user not found")
        return user

    def create(self, uid, data, password):
        self._check_timezone(data.get("timezone"))
        generated = password is None
        password = password or temporary_password()
        self._check_password(password, data["email"])
        row = self.repo.create(uid, data, hash_password(password))
        if row is None:
            raise Conflict({"message": "an active user already has that email", "field": "email"})
        self.repo.commit()
        # A generated password is shown once, here; it is never stored or returned again
        return {**row, **({"temporary_password": password} if generated else {})}

    def update(self, uid, user_id, fields):
        self._manageable(uid, self._active(user_id))
        self._check_timezone(fields.get("timezone"))
        row = self.repo.update(uid, user_id, fields)
        if row is None:
            raise Conflict({"message": "an active user already has that email", "field": "email"})
        self.repo.commit()
        return row

    def set_active(self, uid, user_id, active):
        target = self._active(user_id)
        self._manageable(uid, target)
        if not active:
            self._check_not_self_or_last_admin(uid, target, "deactivate")
            self.repo.revoke_sessions(user_id, "admin")  # a suspended user loses their sessions now
        self.repo.set_active(uid, user_id, active)
        self.repo.commit()
        return self.repo.get(user_id)

    def unlock(self, uid, user_id):
        self._manageable(uid, self._active(user_id))
        self.repo.unlock(uid, user_id)
        self.repo.commit()
        return self.repo.get(user_id)

    def reset_password(self, uid, user_id, password):
        target = self._active(user_id)
        self._manageable(uid, target)
        generated = password is None
        password = password or temporary_password()
        self._check_password(password, target["email"])
        # Temporary: the user must choose their own at next sign-in. Old sessions end.
        self.repo.set_password(uid, user_id, hash_password(password), must_change=True)
        self.repo.revoke_sessions(user_id, "admin")
        self.repo.commit()
        return {"user_id": user_id, **({"temporary_password": password} if generated else {})}

    def logout_all(self, uid, user_id):
        self._manageable(uid, self._active(user_id))
        revoked = self.repo.revoke_sessions(user_id, "admin")
        self.repo.commit()
        return {"revoked": revoked}

    def delete(self, uid, user_id):
        target = self._active(user_id)
        self._manageable(uid, target)
        self._check_not_self_or_last_admin(uid, target, "delete")
        self.repo.delete(uid, user_id)
        self.repo.commit()

    def restore(self, uid, user_id):
        target = self.get(user_id)
        if target["deleted_at"] is None:
            raise NotFound("deleted user not found")
        row = self.repo.restore(uid, user_id)
        if row is None:
            raise Conflict({"message": "another active user took that email", "field": "email"})
        self.repo.commit()
        return row

    def sessions(self, user_id):
        self.get(user_id)
        return self.repo.sessions(user_id)

    def login_history(self, user_id, page, page_size):
        self.get(user_id)
        return self._page(self.repo.login_history, user_id, page, page_size)

    def history(self, user_id, page, page_size):
        self.get(user_id)
        return self._page(self.repo.history, user_id, page, page_size)

    # --- me (no users permission needed) ---

    def update_me(self, uid, fields):
        self._check_timezone(fields.get("timezone"))
        row = self.repo.update(uid, uid, fields)
        self.repo.commit()
        return row

    def change_password(self, uid, current, new):
        if not verify_password(current, self.repo.password_hash(uid) or ""):
            raise Invalid({"message": "the current password is not correct", "field": "current_password"})
        self._check_password(new, self.get(uid)["email"])
        if verify_password(new, self.repo.password_hash(uid)):
            raise Invalid({"message": "choose a password different from the current one", "rules": ["same_as_current"]})
        self.repo.set_password(uid, uid, hash_password(new), must_change=False)
        self.repo.revoke_sessions(uid, "logout")  # every device signs in again with the new password
        self.repo.commit()

    # --- rules ---

    def _active(self, user_id):
        user = self.get(user_id)
        if user["deleted_at"] is not None:
            raise NotFound("user not found")
        return user

    def _manageable(self, uid, target):
        """No one manages a user with more access than they have (the super admin is exempt)."""
        if self.repo.is_super_admin(uid):
            return
        if self.repo.is_super_admin(target["id"]) or self.repo.permission_set(target["id"]) - self.repo.permission_set(uid):
            raise Forbidden("this user has access you don't have")

    def _check_not_self_or_last_admin(self, uid, target, action):
        if target["id"] == uid:
            raise Invalid(f"you can't {action} your own user")
        # Someone active must still be able to administer users, or nobody can fix access anymore
        if self.repo.has_permission(target["id"], "users", "update") and self.repo.other_user_admins(target["id"]) == 0:
            raise Conflict({"message": "this is the last user who can administer users"})

    def _check_password(self, password, email):
        problems = password_problems(password, email)
        if problems:
            raise Invalid({"message": "the password doesn't meet the policy", "field": "password", "rules": problems})

    def _check_timezone(self, timezone):
        if timezone is not None and not self.repo.timezone_exists(timezone):
            raise Invalid({"message": "unknown timezone", "field": "timezone"})

    @staticmethod
    def _page(fetch, user_id, page, page_size):
        rows = fetch(user_id, page_size + 1, (page - 1) * page_size)
        return {"items": rows[:page_size], "page": page, "page_size": page_size, "has_more": len(rows) > page_size}
