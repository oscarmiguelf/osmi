from app.application.errors import Conflict, Forbidden, Invalid, NotFound
from app.application.ports.branch_repository import BranchRepository

MODULE = "branches"


class BranchService:
    def __init__(self, repo: BranchRepository):
        self.repo = repo

    def list_branches(self, uid, include_deleted):
        # Without branches.read you only see your own branches (what the login already gives you)
        if not self.repo.has_permission(uid, MODULE, "read"):
            return self.repo.branches_of(uid)
        return self.repo.list_all(include_deleted)

    def get(self, bid):
        branch = self.repo.get(bid)
        if branch is None:
            raise NotFound("branch not found")
        return branch

    def create(self, uid, data):
        self._check_unique(data["name"], data["code"], None)
        row = self.repo.create(uid, data)
        if row is None:  # someone took the name or code between the check and the insert
            raise Conflict({"message": "name or code already used by an active branch"})
        # Whoever creates a branch belongs to it (same transaction: no branch without its creator)
        self.repo.assign(uid, uid, [row["id"]])
        self.repo.commit()
        return self.repo.get(row["id"])

    def update(self, uid, bid, fields):
        branch = self._active(bid)
        if "code" in fields and fields["code"] != branch["code"] and not branch["code_editable"]:
            # The code is printed in every folio already issued (SUC1-000123)
            raise Conflict({"message": "the code can't change once the branch has issued folios", "field": "code"})
        self._check_unique(fields.get("name"), fields.get("code"), bid)
        row = self.repo.update(uid, bid, fields)
        if row is None:
            raise Conflict({"message": "name or code already used by an active branch"})
        self.repo.commit()
        return row

    def delete(self, uid, bid):
        self._active(bid)
        blockers = {k: v for k, v in self.repo.delete_blockers(bid).items() if v}
        if blockers:
            raise Conflict({"message": "the branch still has work in progress", "blockers": blockers})
        self.repo.delete(uid, bid)
        self.repo.commit()

    def restore(self, uid, bid):
        branch = self.get(bid)
        if branch["deleted_at"] is None:
            raise NotFound("deleted branch not found")
        self._check_unique(branch["name"], branch["code"], bid)
        row = self.repo.restore(uid, bid)
        if row is None:
            raise Conflict({"message": "name or code already used by an active branch"})
        self.repo.commit()
        return row

    def history(self, bid, page, page_size):
        self.get(bid)
        rows = self.repo.history(bid, page_size + 1, (page - 1) * page_size)
        return {"items": rows[:page_size], "page": page, "page_size": page_size, "has_more": len(rows) > page_size}

    def members(self, bid):
        self.get(bid)
        return self.repo.members(bid)

    def add_member(self, uid, bid, user_id):
        self._active(bid)
        self._check_user(user_id)
        self._check_escalation(uid, {bid})
        if not self.repo.assign(uid, user_id, [bid]):
            raise Conflict({"message": "user already assigned to this branch"})
        self.repo.commit()

    def remove_member(self, uid, bid, user_id):
        self.get(bid)
        self._check_escalation(uid, {bid})
        self._check_open_work(user_id, [bid])
        if not self.repo.unassign(uid, user_id, [bid]):
            raise NotFound("user is not in this branch")
        self.repo.commit()

    def branches_of(self, user_id):
        self._check_user(user_id)
        return self.repo.branches_of(user_id)

    def set_branches(self, uid, user_id, branch_ids):
        """Replace the user's active branches with exactly branch_ids (one transaction)."""
        self._check_user(user_id)
        wanted = set(branch_ids)
        if wanted - self.repo.active_branch_ids(list(wanted)):
            raise Invalid("unknown or deleted branch")
        current = {b["id"] for b in self.repo.branches_of(user_id)}
        added, removed = wanted - current, current - wanted
        self._check_escalation(uid, added | removed)
        self._check_open_work(user_id, list(removed))
        self.repo.unassign(uid, user_id, list(removed))
        self.repo.assign(uid, user_id, list(added))
        self.repo.commit()
        return self.repo.branches_of(user_id)

    def _active(self, bid):
        branch = self.get(bid)
        if branch["deleted_at"] is not None:
            raise NotFound("branch not found")
        return branch

    def _check_unique(self, name, code, exclude_id):
        taken = self.repo.conflicts(name, code, exclude_id)
        if taken:
            raise Conflict({"message": f"{' and '.join(taken)} already used by an active branch", "fields": taken})

    def _check_user(self, user_id):
        if not self.repo.user_exists(user_id):
            raise NotFound("user not found")

    def _check_escalation(self, uid, branch_ids):
        # You can only give or take away branches you belong to yourself (the super admin is exempt)
        if not branch_ids or self.repo.is_super_admin(uid):
            return
        mine = {b["id"] for b in self.repo.branches_of(uid)}
        if branch_ids - mine:
            raise Forbidden("you can only assign or remove branches you belong to")

    def _check_open_work(self, user_id, branch_ids):
        if not branch_ids:
            return
        open_work = {k: v for k, v in self.repo.open_work(user_id, branch_ids).items() if v}
        if open_work:
            raise Conflict({"message": "the user has work open in that branch; close it first", "open": open_work})
