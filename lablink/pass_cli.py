"""Issue a short-lived campus pass from a trusted administrator terminal."""
import argparse
import time
from .auth import encode, signing_key
from .catalog import CATALOG

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("owner", help="Unique campus user ID, e.g. student-2117")
    parser.add_argument("role", choices=["student", "faculty"])
    parser.add_argument("--department", choices=sorted({u["department"] for u in CATALOG}))
    args = parser.parse_args()
    if args.role == "faculty" and not args.department:
        parser.error("Faculty passes require a department")
    print(encode(dict(space="campus-main", owner=args.owner, role=args.role, dept=args.department or "",
                      demo=False, purpose="pass", exp=int(time.time())+3600), signing_key()))

