"""
The logging.cfg template must build the handlers it declares.

Why this exists
---------------
``launch_server.py`` bootstraps a fresh checkout by copying
``src/resources/logging.cfg`` over ``src/conf/logging.cfg`` whenever
``serverconf.py`` is absent -- which is every from-source first launch,
because serverconf.py is gitignored. For years the template passed
``'maxBytes=31457280'`` and ``'backupCount=15'`` as *positional strings*,
so RotatingFileHandler received ``maxBytes='maxBytes=31457280'`` and the
first launch died with ``TypeError: '>' not supported between instances
of 'str' and 'int'``.

No developer machine ever saw it: an installed serverconf.py suppresses
the bootstrap, and the tracked conf/logging.cfg was already correct. The
Docker path writes serverconf.py before boot and never runs the bootstrap
either. Only a genuinely fresh from-source install hit the broken file --
the one audience that cannot debug it.

So this test evaluates the handler args of BOTH tracked cfg files exactly
the way ``logging.config.fileConfig`` does, instantiates the handler with
them, and pins the template to the installed file so they cannot drift
apart again.
"""

import configparser
import logging
import logging.handlers
import os
import sys
import tempfile

# PaintomicsServer/  <- src/  <- tests/  <- this file
SERVER_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CFG_FILES = (
    os.path.join(SERVER_ROOT, "src", "conf", "logging.cfg"),
    os.path.join(SERVER_ROOT, "src", "resources", "logging.cfg"),
)

_PASSED = []
_FAILED = []


def _check(name, fn):
    import traceback
    try:
        fn()
        _PASSED.append(name)
        print("PASS  " + name)
    except Exception:
        _FAILED.append((name, traceback.format_exc()))
        print("FAIL  " + name)


def _file_handler_args(path):
    """The evaluated args tuple, exactly as logging.config computes it."""
    cp = configparser.ConfigParser()
    read = cp.read(path)
    assert read, "%s is missing or unreadable" % path
    raw = cp.get("handler_fileHandler", "args")
    # This mirrors logging/config.py _install_handlers: eval in the logging
    # module's namespace, which is what makes os/sys/handlers resolvable.
    return eval(raw, vars(logging))


def test_file_handler_args_are_numeric():
    """maxBytes and backupCount must arrive as ints, not decorative strings."""
    for path in CFG_FILES:
        args = _file_handler_args(path)
        assert len(args) == 4, (
            "%s: expected (filename, mode, maxBytes, backupCount), got %r"
            % (path, args)
        )
        assert isinstance(args[2], int) and isinstance(args[3], int), (
            "%s: maxBytes/backupCount evaluated to %r -- RotatingFileHandler "
            "will refuse these on the first launch" % (path, args[2:])
        )


def test_file_handler_actually_constructs():
    """Run the exact constructor call that crashed, against a temp file."""
    for path in CFG_FILES:
        args = _file_handler_args(path)
        with tempfile.TemporaryDirectory() as tmp:
            handler = logging.handlers.RotatingFileHandler(
                os.path.join(tmp, "application.log"), *args[1:]
            )
            handler.close()


def test_template_matches_installed_file():
    """The bootstrap copies the template over conf/; divergence means a
    fresh install boots a different logging setup than every dev checkout."""
    installed = _file_handler_args(CFG_FILES[0])
    template = _file_handler_args(CFG_FILES[1])
    assert installed == template, (
        "conf/logging.cfg and resources/logging.cfg disagree on the file "
        "handler: %r vs %r" % (installed, template)
    )


def main():
    print("logging.cfg template test")
    print("server root: %s\n" % SERVER_ROOT)

    tests = [
        test_file_handler_args_are_numeric,
        test_file_handler_actually_constructs,
        test_template_matches_installed_file,
    ]
    for t in tests:
        _check(t.__name__, t)

    print()
    print("Passed: %d / %d" % (len(_PASSED), len(_PASSED) + len(_FAILED)))
    if _FAILED:
        for name, msg in _FAILED:
            print("\n--- %s ---\n%s" % (name, msg))
        sys.exit(1)


if __name__ == "__main__":
    main()
