"""Throwaway probe: connect to the session bus, open SQLite read-only, do one lookup, exit.
Same steps as spike/rust-bench/src/main.rs. Uses python-dbus with the GLib main loop, like the KDE template."""
import sqlite3
import sys

import dbus
from dbus.mainloop.glib import DBusGMainLoop

DBusGMainLoop(set_as_default=True)
dbus.SessionBus()
db = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
row = db.execute("select trans_list from simple_translation where written_rep = ? limit 1", (sys.argv[2],)).fetchone()
print(row[0] if row else None)
print([l for l in open("/proc/self/status") if l.startswith("VmHWM")][0].strip())
