"""CoDIR IA Python runtime compatibility probe.

Exit codes are stable contracts consumed by native launchers:
  0  compatible standard CPython 3.11..3.14
  10 version too old
  11 version too new
  12 free-threaded/no-GIL build (unsupported by this release)
  13 non-CPython implementation
  14 native Windows ARM64 interpreter (the locked dependencies need the x64 build, run by Windows emulation)
  15 x86_64 interpreter on macOS (v17.0 supports Apple silicon Macs only)
  16 Python 3.14 on macOS (watchdog 6.0.0 publishes no macOS binary for it)
  17 32-bit Python on Windows (the locked dependencies need a 64-bit Python)
"""
from __future__ import annotations

from dataclasses import dataclass
import platform
import sys
import sysconfig
from typing import Sequence

MIN_VERSION = (3, 11)   # 9.4.65 — pandas 3.0.3 et numpy 2.4.6 du verrou exigent Python >= 3.11
MAX_VERSION = (3, 14)

EXIT_OK = 0
EXIT_TOO_OLD = 10
EXIT_TOO_NEW = 11
EXIT_FREE_THREADED = 12
EXIT_NON_CPYTHON = 13
# 9.4.65 — essai natif du 20/10/2026 et décision de l'éditeur : quatre dépendances verrouillées (cryptography,
# httptools, pyarrow, watchdog) ne publient aucun binaire Windows ARM64 ; cryptography 50 n'en publie plus pour
# les Mac Intel ; watchdog 6.0.0 n'en publie pas pour Python 3.14 sous macOS.
EXIT_WINDOWS_ARM64 = 14
EXIT_MACOS_INTEL = 15
EXIT_MACOS_PY314 = 16
EXIT_WINDOWS_32BIT = 17   # 9.4.65 — cinquième vérification : pandas, pyarrow, cryptography et httptools n'ont pas de binaire win32


@dataclass(frozen=True)
class RuntimeAssessment:
    status: str
    exit_code: int
    message: str


def evaluate_runtime(
    version: Sequence[int],
    *,
    implementation: str = "CPython",
    gil_disabled: bool = False,
    os_platform: str = "",
    machine: str = "",
    build_platform: str = "",
) -> RuntimeAssessment:
    """Return the deterministic CoDIR IA compatibility decision."""
    major_minor = tuple(int(x) for x in version[:2])
    if implementation.casefold() != "cpython":
        return RuntimeAssessment(
            "NON_CPYTHON",
            EXIT_NON_CPYTHON,
            f"implementation {implementation} unsupported; CPython required",
        )
    if major_minor < MIN_VERSION:
        return RuntimeAssessment(
            "TOO_OLD",
            EXIT_TOO_OLD,
            f"Python {major_minor[0]}.{major_minor[1]} is older than 3.11",
        )
    if major_minor > MAX_VERSION:
        return RuntimeAssessment(
            "TOO_NEW",
            EXIT_TOO_NEW,
            f"Python {major_minor[0]}.{major_minor[1]} is newer than validated maximum 3.14",
        )
    if gil_disabled:
        return RuntimeAssessment(
            "FREE_THREADED",
            EXIT_FREE_THREADED,
            "free-threaded/no-GIL build unsupported; install the standard build",
        )
    plat = (os_platform or "").lower()
    mach = (machine or "").lower()
    # Windows : l'architecture de l'interpréteur se lit dans sysconfig.get_platform() (« win-amd64 », « win-arm64 »),
    # celle dont pip déduit les binaires à installer. platform.machine() renvoie le processeur de la machine
    # (« ARM64 » aussi pour un Python x64 émulé sous Windows ARM) et ne doit pas servir ici.
    build = (build_platform or "").lower()
    if plat.startswith("win") and build.endswith(("-arm64", "_arm64")):
        return RuntimeAssessment(
            "WINDOWS_ARM64",
            EXIT_WINDOWS_ARM64,
            "native Windows ARM64 Python: four locked dependencies publish no ARM64 binary; use the x64 Python (Windows emulation)",
        )
    if plat.startswith("win") and build == "win32":
        return RuntimeAssessment(
            "WINDOWS_32BIT",
            EXIT_WINDOWS_32BIT,
            "32-bit Python on Windows: the locked dependencies need a 64-bit Python",
        )
    if plat == "darwin" and mach in ("x86_64", "amd64", "i386"):
        return RuntimeAssessment(
            "MACOS_INTEL",
            EXIT_MACOS_INTEL,
            "x86_64 Python on macOS: CoDIR IA v17.0 supports Apple silicon Macs only; use an arm64 Python",
        )
    if plat == "darwin" and major_minor == (3, 14):
        return RuntimeAssessment(
            "MACOS_PY314",
            EXIT_MACOS_PY314,
            "Python 3.14 on macOS: a locked dependency publishes no binary for it; use Python 3.11 to 3.13",
        )
    return RuntimeAssessment(
        "OK",
        EXIT_OK,
        f"standard CPython {major_minor[0]}.{major_minor[1]} supported",
    )


def _print_field(name: str, value: object) -> None:
    print(f"{name}={value}")


def main() -> int:
    gil_disabled = bool(sysconfig.get_config_var("Py_GIL_DISABLED") or 0)
    assessment = evaluate_runtime(
        sys.version_info[:2],
        implementation=platform.python_implementation(),
        gil_disabled=gil_disabled,
        os_platform=sys.platform,
        machine=platform.machine(),
        build_platform=sysconfig.get_platform(),
    )
    _print_field("CODIR_PY_STATUS", assessment.status)
    _print_field("CODIR_PY_VERSION", platform.python_version())
    _print_field("CODIR_PY_EXECUTABLE", sys.executable)
    _print_field("CODIR_PY_IMPLEMENTATION", platform.python_implementation())
    _print_field("CODIR_PY_FREE_THREADED", int(gil_disabled))
    _print_field("CODIR_PY_ARCH", platform.machine())
    _print_field("CODIR_PY_BUILD_PLATFORM", sysconfig.get_platform())
    _print_field("CODIR_PY_MESSAGE", assessment.message)
    return assessment.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
