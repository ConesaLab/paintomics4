"""Release hygiene: no secret may ever be committed.

Run from `PaintomicsServer/`:

    python -m src.tests.test_release_hygiene

Exists because PaintomicsServer/src/conf/serverconf.py was tracked with a live
Dashscope API key as a hardcoded default. The .gitignore entry meant to prevent
that was `/serverconf.py`, whose leading slash matches only the repo root, so
it never applied to the real config.

These tests scan tracked files only. Anything gitignored is by definition not
being published.
"""
import os
import re
import subprocess
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

_PASSED = []
_FAILED = []

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))


def _check(name, fn):
    try:
        fn()
        _PASSED.append(name)
        print(f"PASS  {name}")
    except AssertionError as exc:
        _FAILED.append((name, str(exc)))
        print(f"FAIL  {name}: {exc}")
    except Exception:
        _FAILED.append((name, traceback.format_exc()))
        print(f"ERROR {name}:\n{traceback.format_exc()}")


def _trackedFiles():
    result = subprocess.run(["git", "-C", _REPO_ROOT, "ls-files", "-z"],
                            capture_output=True, universal_newlines=True, check=True)
    return [p for p in result.stdout.split("\0") if p]


# Token shapes that indicate a real credential rather than a placeholder.
# Each is anchored on a provider prefix so ordinary prose cannot match.
_SECRET_PATTERNS = [
    ("OpenAI-style API key",     re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}")),
    ("Dashscope service key",    re.compile(r"\bsk-sp-[A-Za-z0-9]{16,}")),
    ("SendGrid API key",         re.compile(r"\bSG\.[A-Za-z0-9_\-]{20,}")),
    ("AWS access key id",        re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("Slack token",              re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]{10,}")),
    ("GitHub token",             re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}")),
    ("Google API key",           re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    ("Private key block",        re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |PGP )?PRIVATE KEY-----")),
]

# Binary and vendored paths that would only produce noise.
_SKIP_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg", ".pdf",
                  ".zip", ".gz", ".woff", ".woff2", ".ttf", ".eot", ".min.js",
                  ".map", ".xlsx", ".pyc")


def test_no_secret_literals_in_tracked_files():
    """The regression that motivated this file."""
    findings = []
    for relativePath in _trackedFiles():
        if relativePath.endswith(_SKIP_SUFFIXES):
            continue
        # This file necessarily contains the patterns it searches for.
        if os.path.basename(relativePath) == "test_release_hygiene.py":
            continue

        fullPath = os.path.join(_REPO_ROOT, relativePath)
        if not os.path.isfile(fullPath):
            continue
        try:
            with open(fullPath, "r", errors="ignore") as handle:
                content = handle.read()
        except OSError:
            continue

        for label, pattern in _SECRET_PATTERNS:
            for match in pattern.finditer(content):
                lineNumber = content.count("\n", 0, match.start()) + 1
                # Show only a prefix so the test output is not itself a leak.
                excerpt = match.group(0)[:12]
                findings.append(f"{relativePath}:{lineNumber}: {label} ({excerpt}...)")

    assert not findings, \
        "secret literals found in tracked files:\n  " + "\n  ".join(findings)


def test_real_server_config_is_not_tracked():
    tracked = _trackedFiles()
    offenders = [p for p in tracked
                 if p.endswith("conf/serverconf.py") or p.endswith("conf/local_serverconf.py")]
    assert not offenders, \
        ("the live server config is tracked and will be published: " + ", ".join(offenders) +
         "\nRun: git rm --cached <path>")


def test_config_template_exists_and_has_no_secret_defaults():
    """Every credential in the template must default to empty."""
    templatePath = os.path.join(
        _REPO_ROOT, "PaintomicsServer", "src", "resources", "example_serverconf.py")
    assert os.path.isfile(templatePath), "config template is missing: " + templatePath

    with open(templatePath) as handle:
        content = handle.read()

    # Any os.getenv default for a credential-shaped name must be "".
    credentialName = re.compile(
        r'os\.getenv\(\s*"([A-Z0-9_]*(?:API_KEY|PASSWORD|TOKEN|SECRET)[A-Z0-9_]*)"\s*,\s*"([^"]*)"')
    offenders = [(name, default) for name, default in credentialName.findall(content) if default]
    assert not offenders, \
        "template has non-empty credential defaults: " + str(offenders)

    for label, pattern in _SECRET_PATTERNS:
        assert not pattern.search(content), f"template contains a {label}"


def test_template_covers_every_setting_the_app_imports():
    """A template missing a key means a fresh deployment crashes on import.

    Collects `from src.conf.serverconf import X, Y` and `from conf.serverconf
    import ...` across the tree and checks each name is defined in the template.
    """
    importPattern = re.compile(
        r"from\s+(?:src\.)?conf\.serverconf\s+import\s+([^\n(]+|\([^)]*\))")

    required = set()
    for relativePath in _trackedFiles():
        if not relativePath.endswith(".py"):
            continue
        # This file documents the import form it searches for, so scanning it
        # would collect the placeholder names out of its own docstring.
        if os.path.basename(relativePath) == "test_release_hygiene.py":
            continue
        fullPath = os.path.join(_REPO_ROOT, relativePath)
        if not os.path.isfile(fullPath):
            continue
        with open(fullPath, "r", errors="ignore") as handle:
            content = handle.read()
        for group in importPattern.findall(content):
            if "*" in group:
                continue
            for name in group.strip("()").replace("\\", " ").split(","):
                name = name.strip().split(" as ")[0].strip()
                if name and name.isidentifier():
                    required.add(name)

    templatePath = os.path.join(
        _REPO_ROOT, "PaintomicsServer", "src", "resources", "example_serverconf.py")
    namespace = {}
    exec(compile(open(templatePath).read(), templatePath, "exec"), namespace)

    missing = sorted(name for name in required if name not in namespace)
    assert not missing, \
        ("the config template does not define settings the application imports, so a "
         "fresh deployment would fail at import: " + ", ".join(missing))


def test_template_is_importable_with_no_environment_set():
    """A deployment with no env vars set must still produce a valid config."""
    templatePath = os.path.join(
        _REPO_ROOT, "PaintomicsServer", "src", "resources", "example_serverconf.py")

    saved = dict(os.environ)
    try:
        for key in list(os.environ):
            if key.startswith(("AI_", "SMTP_", "PAINTOMICS_", "MONGODB_", "SERVER_", "EMAIL_")):
                del os.environ[key]
        namespace = {}
        exec(compile(open(templatePath).read(), templatePath, "exec"), namespace)
    finally:
        os.environ.clear()
        os.environ.update(saved)

    assert namespace["SERVER_ALLOW_DEBUG"] is False, \
        "template must not default to debug mode in production"
    assert namespace["KEGG_DATA_DIR"].endswith("/"), \
        "KEGG_DATA_DIR must end in a separator; callers concatenate onto it"
    assert namespace["CLIENT_TMP_DIR"].endswith("/"), \
        "CLIENT_TMP_DIR must end in a separator; callers concatenate onto it"
    for provider, settings in namespace["AI_PROVIDERS"].items():
        assert settings["api_key"] == "", \
            f"provider '{provider}' has a non-empty api_key default"


def main():
    tests = [
        test_no_secret_literals_in_tracked_files,
        test_real_server_config_is_not_tracked,
        test_config_template_exists_and_has_no_secret_defaults,
        test_template_covers_every_setting_the_app_imports,
        test_template_is_importable_with_no_environment_set,
    ]
    for t in tests:
        _check(t.__name__, t)

    print()
    print(f"Passed: {len(_PASSED)} / {len(_PASSED)+len(_FAILED)}")
    if _FAILED:
        for name, msg in _FAILED:
            print(f"  - {name}: {msg.splitlines()[0] if msg else ''}")
        sys.exit(1)


if __name__ == "__main__":
    main()
