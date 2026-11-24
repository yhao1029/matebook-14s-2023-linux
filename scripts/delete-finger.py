"""Delete one fprintd record on a single claimed D-Bus connection."""
import os
import re
import sys
from gi.repository import Gio, GLib

if len(sys.argv) != 3 or os.geteuid() != 0 or sys.argv[1] != os.environ.get("SUDO_USER"):
    raise SystemExit("Use sudo from the account that owns the fingerprint")
user, finger = sys.argv[1:]
if not re.fullmatch(r"(left|right)-(thumb|(?:index|middle|ring|little)-finger)", finger):
    raise SystemExit("Invalid finger")
bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
name = "net.reactivated.Fprint"


def call(path, interface, method, value=None):
    args = GLib.Variant("(s)", (value,)) if value is not None else None
    return bus.call_sync(name, path, name + "." + interface, method,
                         args, None, Gio.DBusCallFlags.NONE, 20000, None)


path = call("/net/reactivated/Fprint/Manager", "Manager", "GetDefaultDevice").unpack()[0]
call(path, "Device", "Claim", user)
try:
    call(path, "Device", "DeleteEnrolledFinger", finger)
finally:
    call(path, "Device", "Release")
