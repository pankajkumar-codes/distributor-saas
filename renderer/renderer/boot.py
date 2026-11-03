"""Makes the bundled native libraries and fonts the ones WeasyPrint uses. Import this
before weasyprint, and only in the renderer: nothing else should load these libraries.

The python3.12 runtime's LD_LIBRARY_PATH puts the base image's /lib64 before
/var/task/lib, and AL2023's glib 2.74 there is too old for the bundled pango 1.58
(undefined symbol g_hash_table_get_values_as_ptr_array). Loading every file in lib/ by
absolute path with RTLD_GLOBAL first means WeasyPrint's dlopen by soname finds the
bundled copy already loaded. A library whose dependencies are not loaded yet fails and is
tried again on the next pass.
"""

import ctypes
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # /var/task on Lambda
LIB = os.path.join(ROOT, "lib")
FONTS_CONF = os.path.join(ROOT, "fonts", "fonts.conf")


def preload(lib_dir: str = LIB) -> list[str]:
    pending = sorted(os.listdir(lib_dir))
    loaded: list[str] = []
    while pending:
        left = []
        for name in pending:
            try:
                ctypes.CDLL(os.path.join(lib_dir, name), mode=ctypes.RTLD_GLOBAL)
                loaded.append(name)
            except OSError:
                left.append(name)
        if len(left) == len(pending):
            raise OSError(f"cannot preload {left}")
        pending = left
    return loaded


os.environ["FONTCONFIG_FILE"] = FONTS_CONF
LOADED = preload()
