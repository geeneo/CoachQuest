"""Copy every CoachQuest table from one database to another: SQLite to Postgres, or back again.

    python -m app.movedb --to postgresql+psycopg://coachquest:PASSWORD@db/coachquest
    python -m app.movedb --from postgresql+psycopg://... --to sqlite:////data/coachquest-from-postgres.db

The source (default: DATABASE_URL) is only read, never changed, so it stays as the way back.
The target gets CoachQuest's tables and must be empty (--replace empties it first). Rows are
copied table by table in foreign-key order and counted on both sides at the end. SQLite doesn't
enforce what Postgres does, so these are fixed on the way and reported:
- text longer than its column: cut to fit;
- NUL characters in text (Postgres refuses them): removed;
- a link to a row that no longer exists (e.g. a comment on a deleted plan): emptied where the
  column may be empty, else the row is left out.
Encrypted columns are copied as they are: keep the same TOKEN_ENCRYPTION_KEY. Steps and the way
back are in docs/postgres.md.
"""

import argparse
import sys
from collections import Counter

from sqlalchemy import String, create_engine, func, inspect, select, text
from sqlalchemy.engine import Engine, make_url

from .config import settings
from .db import Base

BATCH = 500


def _engine(url: str) -> Engine:
    connect = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return create_engine(url, connect_args=connect)


def _safe(url: str) -> str:
    return make_url(url).render_as_string(hide_password=True)


def _counts(eng: Engine) -> dict[str, int]:
    have = set(inspect(eng).get_table_names())
    with eng.connect() as conn:
        return {
            t.name: conn.scalar(select(func.count()).select_from(t))
            for t in Base.metadata.sorted_tables
            if t.name in have
        }


def copy(source_url: str, target_url: str, replace: bool = False, log=print) -> dict:
    """Copy all tables; returns {"tables": {name: (source, copied)}, "fixes": Counter, "ok": bool}."""
    if make_url(source_url) == make_url(target_url):
        raise SystemExit("Source and target are the same database")
    src, dst = _engine(source_url), _engine(target_url)
    src_tables = set(inspect(src).get_table_names())
    if "users" not in src_tables:
        raise SystemExit(f"{_safe(source_url)} has no CoachQuest data (no users table)")
    if replace:
        Base.metadata.drop_all(dst)
    Base.metadata.create_all(dst)
    full = {name: n for name, n in _counts(dst).items() if n}
    if full:
        raise SystemExit(f"The target isn't empty ({full}); use --replace to empty it first")

    to_pg = dst.dialect.name == "postgresql"
    fixes: Counter = Counter()
    kept: dict[str, set] = {}  # table -> primary keys copied, to check links against
    report = {}
    with src.connect() as s, dst.begin() as d:
        for table in Base.metadata.sorted_tables:
            if table.name not in src_tables:
                report[table.name] = (0, 0)
                continue
            have = {c["name"] for c in inspect(src).get_columns(table.name)}
            cols = [c for c in table.columns if c.name in have]
            pk = [c.name for c in table.primary_key.columns]
            links = [
                (fk.parent.name, fk.column.table.name, fk.parent.nullable)
                for fk in table.foreign_keys
                if fk.parent.name in have
            ]
            limits = {c.name: c.type.length for c in cols if isinstance(c.type, String) and c.type.length}
            texts = [c.name for c in cols if isinstance(c.type, String)]
            order = [table.c[name] for name in pk if name in have]
            result = s.execution_options(stream_results=True).execute(select(*cols).order_by(*order))
            read = copied = 0
            ids = kept.setdefault(table.name, set())
            while rows := result.fetchmany(BATCH):
                batch = []
                for row in rows:
                    read += 1
                    r = dict(row._mapping)
                    for name in texts:
                        v = r.get(name)
                        if isinstance(v, str):
                            if to_pg and "\x00" in v:
                                r[name] = v = v.replace("\x00", "")
                                fixes[f"{table.name}.{name}: NUL characters removed"] += 1
                            if name in limits and len(v) > limits[name]:
                                r[name] = v[: limits[name]]
                                fixes[f"{table.name}.{name}: cut to {limits[name]} characters"] += 1
                    skip = False
                    for col, target, nullable in links:
                        v = r.get(col)
                        if v is not None and v not in kept.get(target, set()):
                            if nullable:
                                r[col] = None
                                fixes[f"{table.name}.{col}: link to a missing {target} row emptied"] += 1
                            else:
                                skip = True
                                fixes[f"{table.name}: row left out (its {target} row is gone)"] += 1
                                break
                    if skip:
                        continue
                    batch.append(r)
                    if len(pk) == 1:
                        ids.add(r[pk[0]])
                if batch:
                    d.execute(table.insert(), batch)
                    copied += len(batch)
            report[table.name] = (read, copied)
            if read:
                log(f"  {table.name:<22} {copied:>8} of {read}")
        if to_pg:
            # Postgres hands out ids from a sequence: start it after the copied ones.
            for table in Base.metadata.sorted_tables:
                pk = list(table.primary_key.columns)
                if len(pk) == 1 and pk[0].autoincrement and pk[0].type.python_type is int:
                    d.execute(
                        text(
                            f"SELECT setval(pg_get_serial_sequence('{table.name}', '{pk[0].name}'), "
                            f"COALESCE(MAX({pk[0].name}), 1), MAX({pk[0].name}) IS NOT NULL) FROM {table.name}"
                        )
                    )
    after = _counts(dst)
    ok = all(after.get(name, 0) == copied for name, (_, copied) in report.items())
    return {"tables": report, "fixes": fixes, "ok": ok}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m app.movedb", description=__doc__.split("\n\n")[0])
    ap.add_argument("--from", dest="source", default=settings.db_url, help="source database (default DATABASE_URL)")
    ap.add_argument("--to", dest="target", required=True, help="target database URL")
    ap.add_argument("--replace", action="store_true", help="empty the target first (drops CoachQuest's tables)")
    args = ap.parse_args(argv)
    print(f"Copying {_safe(args.source)}\n     to {_safe(args.target)}")
    out = copy(args.source, args.target, args.replace)
    total_read = sum(r for r, _ in out["tables"].values())
    total_copied = sum(c for _, c in out["tables"].values())
    print(f"\n{total_copied} of {total_read} rows copied in {len(out['tables'])} tables.")
    if out["fixes"]:
        print("Fixed on the way:")
        for what, n in sorted(out["fixes"].items()):
            print(f"  {n:>6} × {what}")
    if not out["ok"]:
        print("CHECK FAILED: the target's row counts don't match what was copied.", file=sys.stderr)
        return 1
    print("Row counts checked: the target matches. The source wasn't changed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
