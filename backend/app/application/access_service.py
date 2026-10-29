from app.application.errors import Conflict, Forbidden, Invalid, NotFound
from app.application.ports.access_repository import AccessRepository

# The module that grants access to this API. Deleting or deactivating it would lock everyone out.
USERS_MODULE = "users"


class AccessService:
    def __init__(self, repo: AccessRepository):
        self.repo = repo

    # --- modules ---

    def list_modules(self, include_inactive, include_deleted):
        return self.repo.list_modules(include_inactive, include_deleted)

    def get_module(self, mid):
        return self._module(mid, include_deleted=True)

    def create_module(self, data, with_crud_permissions):
        row = self.repo.create_module(data)
        if row is None:
            self._conflict(self.repo.module_by_code(data["code"]), "/modules/{id}/restore")
        if with_crud_permissions:
            self.repo.create_crud_permissions(row["id"])
        self.repo.commit()
        return self.get_module(row["id"])

    def update_module(self, mid, fields):
        module = self._module(mid)
        if module["code"] == USERS_MODULE and fields.get("is_active") is False:
            raise Invalid("the users module cannot be deactivated")
        self.repo.update_module(mid, fields)
        self.repo.commit()
        return self.get_module(mid)

    def delete_module(self, uid, mid):
        if self._module(mid)["code"] == USERS_MODULE:
            raise Invalid("the users module cannot be deleted")
        self.repo.delete_module(uid, mid)
        self.repo.commit()

    def restore_module(self, mid):
        if not self.repo.restore_module(mid):
            raise NotFound("deleted module not found")
        self.repo.commit()
        return self.get_module(mid)

    # --- permissions ---

    def list_permissions(self, mid, include_deleted):
        return self._module(mid, include_deleted)["permissions"]

    def create_permission(self, mid, data):
        self._module(mid)
        row = self.repo.create_permission(mid, data)
        if row is None:
            self._conflict(self.repo.permission_by_code(mid, data["code"]), "/permissions/{id}/restore")
        self.repo.commit()
        return row

    def update_permission(self, pid, fields):
        row = self.repo.update_permission(pid, fields)
        if row is None:
            raise NotFound("permission not found")
        self.repo.commit()
        return row

    def delete_permission(self, uid, pid):
        permission = self.repo.get_permission(pid)
        if permission is None:
            raise NotFound("permission not found")
        if permission["module_code"] == USERS_MODULE:
            raise Invalid("permissions of the users module cannot be deleted")
        self.repo.delete_permission(uid, pid)
        self.repo.commit()

    def restore_permission(self, pid):
        if not self.repo.restore_permission(pid):
            raise NotFound("deleted permission not found")
        self.repo.commit()
        return self.repo.get_permission(pid)

    # --- user access ---

    def get_access(self, target):
        if not self.repo.user_exists(target):
            raise NotFound("user not found")
        return self.repo.user_access(target)

    def set_access(self, uid, target, modules):
        """modules: [(module_id, permission_ids)]. Replaces the user's whole access (non-deleted modules)."""
        if not self.repo.user_exists(target):
            raise NotFound("user not found")
        grants = {mid: set(pids) for mid, pids in modules}
        if len(grants) != len(modules):
            raise Invalid("a module is listed more than once")
        want_m = set(grants)
        want_p = set().union(*grants.values())
        if want_m - self.repo.existing_modules(list(want_m)):
            raise Invalid("unknown or deleted module")
        owners = self.repo.permission_modules(list(want_p))
        for mid, pids in grants.items():
            for pid in pids:
                if owners.get(pid) != mid:
                    raise Invalid(f"permission {pid} does not exist or does not belong to module {mid}")

        # No privilege escalation: you can only add or remove grants you hold yourself.
        if not self.repo.is_super_admin(uid):
            cur_m, cur_p = self.repo.user_grants(target)
            my_m, my_p = self.repo.user_grants(uid)
            if (cur_m ^ want_m) - my_m or (cur_p ^ want_p) - my_p:
                raise Forbidden("you can only grant or revoke modules and permissions you hold")

        self.repo.replace_grants(uid, target, list(want_m), list(want_p))
        if not self.repo.users_admin_exists():  # raising here rolls the whole change back
            raise Invalid("this change would leave no active user able to manage access")
        self.repo.commit()
        return self.repo.user_access(target)

    def _module(self, mid, include_deleted=False):
        rows = self.repo.list_modules(True, include_deleted, mid)
        if not rows:
            raise NotFound("module not found")
        return rows[0]

    def _conflict(self, existing, restore_path):
        if existing and existing["deleted_at"]:
            path = restore_path.replace("{id}", str(existing["id"]))
            raise Conflict(f"code already used by a deleted item; restore it with POST {path}")
        raise Conflict("code already in use")
