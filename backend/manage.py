"""Create and manage portal users.

Run with the backend venv, from the backend folder:

  venv/bin/python manage.py add-employee <username> <password> ["Full Name"] [role]
  venv/bin/python manage.py add-client   <username> <password> ["Company"]
  venv/bin/python manage.py set-password  employee|client <username> <password>
  venv/bin/python manage.py deactivate    employee|client <username>
  venv/bin/python manage.py list

Usernames are stored lowercase. Re-adding an existing username updates it.
"""
import sys
from contextlib import closing
from datetime import datetime, timezone

from app import db, hash_pw  # reuses the same DB path and hashing


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def add(kind, username, password, extra="", role="staff"):
    table = "employees" if kind == "employee" else "clients"
    u = username.strip().lower()
    with closing(db()) as conn:
        if table == "employees":
            conn.execute(
                "INSERT INTO employees (username,password_hash,name,role,active,created_at) VALUES (?,?,?,?,1,?) "
                "ON CONFLICT(username) DO UPDATE SET password_hash=excluded.password_hash,"
                "name=excluded.name,role=excluded.role,active=1",
                (u, hash_pw(password), extra, role, _now()))
        else:
            conn.execute(
                "INSERT INTO clients (username,password_hash,company,active,created_at) VALUES (?,?,?,1,?) "
                "ON CONFLICT(username) DO UPDATE SET password_hash=excluded.password_hash,"
                "company=excluded.company,active=1",
                (u, hash_pw(password), extra, _now()))
        conn.commit()
    print("Saved %s: %s" % (kind, u))


def set_password(kind, username, password):
    table = "employees" if kind == "employee" else "clients"
    with closing(db()) as conn:
        cur = conn.execute("UPDATE %s SET password_hash=? WHERE username=?" % table,
                           (hash_pw(password), username.strip().lower()))
        conn.commit()
    print("Updated" if cur.rowcount else "No such user", username)


def deactivate(kind, username):
    table = "employees" if kind == "employee" else "clients"
    with closing(db()) as conn:
        cur = conn.execute("UPDATE %s SET active=0 WHERE username=?" % table, (username.strip().lower(),))
        conn.commit()
    print("Deactivated" if cur.rowcount else "No such user", username)


def listing():
    with closing(db()) as conn:
        print("Employees:")
        for r in conn.execute("SELECT username,name,role,active FROM employees ORDER BY username"):
            print("  %s  (%s, %s)%s" % (r["username"], r["name"] or "-", r["role"], "" if r["active"] else "  [inactive]"))
        print("Clients:")
        for r in conn.execute("SELECT username,company,active FROM clients ORDER BY username"):
            print("  %s  (%s)%s" % (r["username"], r["company"] or "-", "" if r["active"] else "  [inactive]"))


def main(argv):
    if not argv:
        print(__doc__)
        return
    cmd = argv[0]
    try:
        if cmd == "add-employee":
            add("employee", argv[1], argv[2], argv[3] if len(argv) > 3 else "", argv[4] if len(argv) > 4 else "staff")
        elif cmd == "add-client":
            add("client", argv[1], argv[2], argv[3] if len(argv) > 3 else "")
        elif cmd == "set-password":
            set_password(argv[1], argv[2], argv[3])
        elif cmd == "deactivate":
            deactivate(argv[1], argv[2])
        elif cmd == "list":
            listing()
        else:
            print(__doc__)
    except IndexError:
        print("Missing arguments.\n")
        print(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
