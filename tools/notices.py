#!/usr/bin/env python3
"""Print THIRD-PARTY-NOTICES: the license texts of every crate that is linked into the program.

Usage: python3 -I tools/notices.py > THIRD-PARTY-NOTICES   (run from the repository root, after one cargo build)
Stdlib only. Build-only and dev-only crates are left out.
"""
import json
import pathlib
import subprocess
import sys

meta = json.loads(subprocess.check_output(
    ["cargo", "metadata", "--format-version", "1", "--locked", "--filter-platform", "x86_64-unknown-linux-gnu"], text=True))
packages = {p["id"]: p for p in meta["packages"]}
nodes = {n["id"]: n for n in meta["resolve"]["nodes"]}

# Walk normal dependency edges only, starting at the program itself.
linked, todo = set(), [meta["resolve"]["root"]]
while todo:
    id = todo.pop()
    if id in linked:
        continue
    linked.add(id)
    todo += [d["pkg"] for d in nodes[id]["deps"] if any(k["kind"] is None for k in d["dep_kinds"])]
linked.discard(meta["resolve"]["root"])

print("This program links the crates below. Each section gives the license text of one crate.")
print("The SQLite library inside libsqlite3-sys is in the public domain and needs no notice.\n")
missing = []
for id in sorted(linked, key=lambda i: packages[i]["name"]):
    p = packages[id]
    folder = pathlib.Path(p["manifest_path"]).parent
    files = sorted(f for f in folder.iterdir() if f.is_file() and f.name.upper().startswith(("LICENSE", "LICENCE", "COPYING", "UNLICENSE", "NOTICE")))
    if not files:
        missing.append(p["name"])
    print("=" * 72)
    print(f"{p['name']} {p['version']} - {p['license']}")
    print(p["repository"] or "")
    for f in files:
        print(f"\n--- {f.name} ---\n")
        print(f.read_text(errors="replace").strip())
    print()

# The one check: every crate must carry a license text, and the main crates must be there.
assert not missing, f"no license file for: {missing}"
names = {packages[i]["name"] for i in linked}
assert {"rusqlite", "zbus", "libsqlite3-sys"} <= names, names
print(f"{len(linked)} crates", file=sys.stderr)
