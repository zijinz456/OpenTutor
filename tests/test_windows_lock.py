"""The Windows lock must satisfy patched core and pyproject requirements."""
from pathlib import Path
import re
import tomllib
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

ROOT = Path(__file__).resolve().parents[1]

def locked_requirements():
    text = (ROOT / "scripts/requirements-windows.lock").read_text(encoding="utf-8-sig")
    logical = re.sub(r"\\\s*\n\s*", " ", text)
    result = {}
    for line in logical.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(" --hash=")
        req = Requirement(parts[0].strip())
        name = canonicalize_name(req.name)
        assert name not in result, "Duplicate lock requirement: " + name
        specs = list(req.specifier)
        assert len(specs) == 1 and specs[0].operator == "==" and "*" not in specs[0].version
        assert len(parts) > 1 and all(re.fullmatch(r"sha256:[0-9a-f]{64}", p.strip()) for p in parts[1:])
        result[name] = specs[0].version
    return result

def assert_satisfied(requirements):
    locked = locked_requirements()
    for text in requirements:
        req = Requirement(text)
        name = canonicalize_name(req.name)
        assert name in locked, "Missing patched dependency: " + name
        assert req.specifier.contains(locked[name]), f"{name}=={locked[name]} violates {req.specifier}"

def test_exact_hashed_lock_satisfies_patched_core():
    core = (ROOT / "apps/api/requirements-core.txt").read_text(encoding="utf-8")
    assert_satisfied(line.strip() for line in core.splitlines() if line.strip() and not line.lstrip().startswith("#"))

def test_lock_satisfies_project_core_metadata_too():
    project = tomllib.loads((ROOT / "apps/api/pyproject.toml").read_text(encoding="utf-8"))
    assert_satisfied(project["project"]["dependencies"])

def test_obsolete_jose_dependency_chain_is_removed():
    locked = locked_requirements()
    assert "pyjwt" in locked
    assert not {"python-jose", "ecdsa", "rsa", "pyasn1"}.intersection(locked)

def test_lock_input_includes_live_core_instead_of_copied_pins():
    data = (ROOT / "scripts/requirements-windows.in").read_text(encoding="utf-8-sig")
    assert "-r ../apps/api/requirements-core.txt" in data


def test_lock_satisfies_windows_specific_security_constraints():
    source = (ROOT / "scripts/requirements-windows.in").read_text(encoding="utf-8")
    assert_satisfied(line.strip() for line in source.splitlines()
                     if line.strip() and not line.lstrip().startswith(("#", "-r")))
