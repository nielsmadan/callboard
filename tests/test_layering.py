import ast
import sys
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import NamedTuple

SOURCE_ROOT = Path(__file__).resolve().parents[1] / "src"
PACKAGE_ROOT = SOURCE_ROOT / "callboard"
PACKAGE = "callboard"

LAYERS: tuple[tuple[str, ...], ...] = (
    ("__init__", "codes", "mentions"),
    ("errors", "models"),
    ("paths", "jsonout", "refs", "config"),
    ("store",),
    ("identity", "conversations"),
    ("receipts", "attachments"),
    ("messages",),
    ("mail",),
    ("cli",),
    ("__main__",),
)

LAYER_OF: Mapping[str, int] = {
    group: index for index, groups in enumerate(LAYERS) for group in groups
}

IMPORTS_ALLOWED: Mapping[str, frozenset[str]] = {
    "__init__": frozenset(),
    "codes": frozenset(),
    "mentions": frozenset(),
    "errors": frozenset({"codes"}),
    "models": frozenset(),
    "jsonout": frozenset({"errors"}),
    "paths": frozenset({"errors"}),
    "refs": frozenset({"errors"}),
    "config": frozenset({"errors"}),
    "attachments": frozenset({"errors", "models"}),
    "store": frozenset({"errors", "models"}),
    "identity": frozenset({"codes", "errors", "models", "store"}),
    "conversations": frozenset({"errors", "models", "refs", "store"}),
    "receipts": frozenset({"conversations", "models"}),
    "messages": frozenset(
        {"attachments", "conversations", "errors", "mentions", "models", "receipts", "store"}
    ),
    "mail": frozenset({"conversations", "errors", "messages", "models", "receipts", "store"}),
    "cli": frozenset(
        {
            "attachments",
            "codes",
            "config",
            "conversations",
            "mail",
            "errors",
            "identity",
            "jsonout",
            "messages",
            "models",
            "paths",
            "receipts",
            "refs",
            "store",
        }
    ),
    "__main__": frozenset({"cli"}),
}

SIBLING_IMPORTS_ALLOWED: Mapping[str, Mapping[str, frozenset[str]]] = {
    "cli": {
        "parsing": frozenset(),
        "presentation": frozenset(),
        "rendering": frozenset(),
        "context": frozenset(),
        "commands": frozenset({"presentation"}),
        "doctor": frozenset({"presentation"}),
        "chat": frozenset({"context", "presentation", "rendering"}),
        "reading": frozenset({"context", "presentation", "rendering"}),
        "dispatch": frozenset({"chat", "commands", "doctor", "parsing", "presentation", "reading"}),
        "__init__": frozenset({"dispatch", "parsing", "presentation"}),
    },
}

PACKAGE_ROOT_IMPORTS_ALLOWED: Mapping[str, frozenset[str]] = {
    "callboard.__main__": frozenset({"callboard.cli"}),
}


def _module_name(path: Path) -> str:
    return ".".join(path.relative_to(SOURCE_ROOT).with_suffix("").parts)


def _group(module: str) -> str:
    return module.removeprefix(f"{PACKAGE}.").split(".")[0]


def _leaf(module: str) -> str:
    return module.rsplit(".", maxsplit=1)[-1]


def _is_internal(name: str) -> bool:
    return name == PACKAGE or name.startswith(f"{PACKAGE}.")


def _resolve(name: str, known: frozenset[str]) -> str | None:
    if name in known:
        return name
    initializer = f"{name}.__init__"
    if initializer in known:
        return initializer
    return None


class _Reference(NamedTuple):
    module: str
    name: str
    level: int


def _references(tree: ast.Module) -> Iterator[_Reference]:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield _Reference(alias.name, "", 0)
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                yield _Reference(node.module or "", alias.name, node.level)


class _Scan(NamedTuple):
    internal: dict[str, tuple[str, ...]]
    external: dict[str, tuple[str, ...]]
    relative: list[str]
    unresolved: list[str]
    package_roots: dict[str, tuple[str, ...]]


def _scan() -> _Scan:
    paths = sorted(PACKAGE_ROOT.rglob("*.py"))
    known = frozenset(_module_name(path) for path in paths)
    internal: dict[str, tuple[str, ...]] = {}
    external: dict[str, tuple[str, ...]] = {}
    relative: set[str] = set()
    unresolved: set[str] = set()
    package_roots: dict[str, set[str]] = {}
    for path in paths:
        source = _module_name(path)
        inside: set[str] = set()
        outside: set[str] = set()
        roots: set[str] = set()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for module, name, level in _references(tree):
            if level:
                relative.add(source)
                continue
            if not _is_internal(module):
                outside.add(module.split(".")[0])
                continue
            if f"{module}.__init__" in known:
                roots.add(module)
            target = _resolve(f"{module}.{name}" if name else module, known) or _resolve(
                module, known
            )
            if target is None:
                unresolved.add(f"{source} -> {module}.{name}" if name else f"{source} -> {module}")
            else:
                inside.add(target)
        internal[source] = tuple(sorted(inside))
        external[source] = tuple(sorted(outside))
        package_roots[source] = roots
    return _Scan(
        internal,
        external,
        sorted(relative),
        sorted(unresolved),
        {source: tuple(sorted(roots)) for source, roots in package_roots.items()},
    )


IMPORTS, EXTERNAL_IMPORTS, RELATIVE_IMPORTS, UNRESOLVED_IMPORTS, PACKAGE_ROOT_IMPORTS = _scan()


def _edges() -> Iterator[tuple[str, str]]:
    for source, targets in IMPORTS.items():
        for target in targets:
            yield source, target


def _leaves_by_group() -> dict[str, set[str]]:
    groups: dict[str, set[str]] = {}
    for name in IMPORTS:
        groups.setdefault(_group(name), set()).add(_leaf(name))
    return groups


def test_every_module_is_assigned_a_layer() -> None:
    assert sorted(name for name in IMPORTS if _group(name) not in LAYER_OF) == []


def test_every_layer_group_exists_in_the_package() -> None:
    assert sorted(LAYER_OF) == sorted({_group(name) for name in IMPORTS})


def test_every_group_states_which_groups_it_may_import() -> None:
    assert sorted(IMPORTS_ALLOWED) == sorted(LAYER_OF)
    unknown = sorted(
        f"{group} -> {target}"
        for group, targets in IMPORTS_ALLOWED.items()
        for target in targets
        if target not in LAYER_OF
    )
    assert unknown == []


def test_stated_allowances_only_reach_a_strictly_lower_layer() -> None:
    violations = sorted(
        f"{group} -> {target}"
        for group, targets in IMPORTS_ALLOWED.items()
        for target in targets
        if LAYER_OF.get(target, len(LAYERS)) >= LAYER_OF.get(group, -1)
    )
    assert violations == []


def test_every_group_holding_several_modules_states_its_sibling_order() -> None:
    missing = sorted(
        f"{group}.{leaf}"
        for group, leaves in _leaves_by_group().items()
        if len(leaves) > 1
        for leaf in leaves
        if leaf not in SIBLING_IMPORTS_ALLOWED.get(group, {})
    )
    assert missing == []


def test_internal_imports_are_absolute() -> None:
    assert RELATIVE_IMPORTS == []


def test_every_internal_import_resolves_to_a_module() -> None:
    assert UNRESOLVED_IMPORTS == []


def test_imports_stay_within_the_stated_group_allowance() -> None:
    violations = sorted(
        f"{source} -> {target}"
        for source, target in _edges()
        if _group(source) != _group(target)
        and _group(target) not in IMPORTS_ALLOWED.get(_group(source), frozenset())
    )
    assert violations == []


def test_sibling_imports_stay_within_the_stated_group_order() -> None:
    violations = sorted(
        f"{source} -> {target}"
        for source, target in _edges()
        if _group(source) == _group(target)
        and _leaf(target)
        not in SIBLING_IMPORTS_ALLOWED.get(_group(source), {}).get(_leaf(source), frozenset())
    )
    assert violations == []


def test_package_root_imports_are_declared() -> None:
    violations = sorted(
        f"{source} -> {root}"
        for source, roots in PACKAGE_ROOT_IMPORTS.items()
        for root in roots
        if root not in PACKAGE_ROOT_IMPORTS_ALLOWED.get(source, frozenset())
    )
    assert violations == []


def test_the_top_level_package_is_never_a_declared_import() -> None:
    declared = sorted(
        source for source, roots in PACKAGE_ROOT_IMPORTS_ALLOWED.items() if PACKAGE in roots
    )
    assert declared == []


def test_runtime_imports_only_the_standard_library() -> None:
    violations = sorted(
        f"{source} -> {name}"
        for source, names in EXTERNAL_IMPORTS.items()
        for name in names
        if name not in sys.stdlib_module_names
    )
    assert violations == []
