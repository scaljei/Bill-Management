"""
deps.py — Dependency checker for BillVault.
Runs at startup, checks Python packages and system binaries,
prints a clear report and prompts to auto-install missing Python packages.
"""

import sys
import subprocess
import shutil
import importlib.metadata
from packaging.version import Version

# ── Required Python packages ──────────────────────────────────────────────────

PYTHON_DEPS = [
    {"package": "flask",        "import": "flask",        "min": "3.0.0"},
    {"package": "pypdf",        "import": "pypdf",        "min": "4.0.0"},
    {"package": "pdf2image",    "import": "pdf2image",    "min": "1.16.0"},
    {"package": "pytesseract",  "import": "pytesseract",  "min": "0.3.10"},
]

# ── Required system binaries ──────────────────────────────────────────────────

SYSTEM_DEPS = [
    {
        "name":    "Tesseract OCR",
        "binary":  "tesseract",
        "version_cmd": ["tesseract", "--version"],
        "install": {
            "darwin":  "brew install tesseract",
            "linux":   "sudo apt install tesseract-ocr   # Debian/Ubuntu\n"
                       "    sudo dnf install tesseract          # Fedora/RHEL\n"
                       "    sudo pacman -S tesseract            # Arch",
            "win32":   "Download from https://github.com/UB-Mannheim/tesseract/wiki\n"
                       "    and add to PATH",
        },
        "required_for": "OCR on scanned/image PDFs",
    },
    {
        "name":    "Poppler (pdftoppm)",
        "binary":  "pdftoppm",
        "version_cmd": ["pdftoppm", "-v"],
        "install": {
            "darwin":  "brew install poppler",
            "linux":   "sudo apt install poppler-utils    # Debian/Ubuntu\n"
                       "    sudo dnf install poppler-utils      # Fedora/RHEL\n"
                       "    sudo pacman -S poppler              # Arch",
            "win32":   "Download from https://github.com/oschwartz10612/poppler-windows/releases\n"
                       "    and add to PATH",
        },
        "required_for": "PDF-to-image conversion (needed by pdf2image)",
    },
]

# ── Colours (disabled on Windows unless ANSICON/WT) ───────────────────────────

def _supports_colour():
    import os
    return sys.platform != "win32" or "WT_SESSION" in os.environ or "ANSICON" in os.environ

RESET = "\033[0m"  if _supports_colour() else ""
BOLD  = "\033[1m"  if _supports_colour() else ""
RED   = "\033[91m" if _supports_colour() else ""
YEL   = "\033[93m" if _supports_colour() else ""
GRN   = "\033[92m" if _supports_colour() else ""
CYN   = "\033[96m" if _supports_colour() else ""
DIM   = "\033[2m"  if _supports_colour() else ""

OK   = f"{GRN}✔{RESET}"
WARN = f"{YEL}⚠{RESET}"
ERR  = f"{RED}✘{RESET}"


# ── Checkers ──────────────────────────────────────────────────────────────────

def check_python_version():
    ok = sys.version_info >= (3, 10)
    ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    return ok, ver


def check_python_package(dep: dict):
    """Returns (status, installed_version_or_None)"""
    try:
        installed = importlib.metadata.version(dep["package"])
        if Version(installed) < Version(dep["min"]):
            return "outdated", installed
        return "ok", installed
    except importlib.metadata.PackageNotFoundError:
        return "missing", None


def check_system_binary(dep: dict):
    """Returns (found: bool, version_str_or_None)"""
    if not shutil.which(dep["binary"]):
        return False, None
    try:
        result = subprocess.run(
            dep["version_cmd"], capture_output=True, text=True, timeout=5
        )
        # Tesseract prints to stderr, pdftoppm to stderr too
        raw = (result.stdout + result.stderr).strip().splitlines()
        ver = raw[0] if raw else "unknown"
        return True, ver
    except Exception:
        return True, "unknown"


# ── Auto-install ──────────────────────────────────────────────────────────────

def auto_install(packages: list[str]) -> bool:
    """Pip-install a list of package specs. Returns True on success."""
    cmd = [sys.executable, "-m", "pip", "install", "--upgrade"] + packages
    print(f"\n{CYN}Running:{RESET} {' '.join(cmd)}\n")
    result = subprocess.run(cmd)
    return result.returncode == 0


# ── Main check ────────────────────────────────────────────────────────────────

def run_checks(auto: bool = False, quiet: bool = False) -> bool:
    """
    Run all dependency checks.
    auto=True  → install missing/outdated Python packages without prompting.
    quiet=True → only print warnings/errors (suppress OK lines).
    Returns True if all critical deps are satisfied after checks (and any installs).
    """
    header = f"\n{BOLD}{'─'*54}{RESET}\n{BOLD}  BillVault — Dependency Check{RESET}\n{BOLD}{'─'*54}{RESET}"
    print(header)

    all_ok = True
    to_install: list[str] = []

    # ── Python version
    py_ok, py_ver = check_python_version()
    if py_ok:
        if not quiet:
            print(f"  {OK} Python {py_ver}")
    else:
        print(f"  {WARN} Python {py_ver}  (3.10+ recommended)")

    # ── Python packages
    print(f"\n  {BOLD}Python packages{RESET}")
    for dep in PYTHON_DEPS:
        status, ver = check_python_package(dep)
        if status == "ok":
            if not quiet:
                print(f"    {OK} {dep['package']} {DIM}v{ver}{RESET}")
        elif status == "outdated":
            print(f"    {WARN} {dep['package']} {DIM}v{ver}{RESET}  {YEL}(min {dep['min']} required){RESET}")
            to_install.append(f"{dep['package']}>={dep['min']}")
            all_ok = False
        else:
            print(f"    {ERR} {dep['package']}  {RED}NOT INSTALLED{RESET}")
            to_install.append(f"{dep['package']}>={dep['min']}")
            all_ok = False

    # ── System binaries
    print(f"\n  {BOLD}System binaries{RESET}")
    missing_system: list[dict] = []
    for dep in SYSTEM_DEPS:
        found, ver = check_system_binary(dep)
        if found:
            if not quiet:
                print(f"    {OK} {dep['name']}  {DIM}{ver}{RESET}")
        else:
            print(f"    {WARN} {dep['name']}  {YEL}not found{RESET}  {DIM}(needed for: {dep['required_for']}){RESET}")
            missing_system.append(dep)
            # System deps are non-fatal — app still works for digital PDFs

    # ── Install prompt / auto-install
    if to_install:
        print()
        if auto:
            ok = auto_install(to_install)
            if ok:
                print(f"\n  {GRN}Packages installed successfully.{RESET}")
                all_ok = True
            else:
                print(f"\n  {RED}Installation failed. Run manually:{RESET}")
                print(f"    pip install {' '.join(to_install)}")
                all_ok = False
        else:
            print(f"  {YEL}Missing/outdated Python packages:{RESET} {', '.join(to_install)}")
            print(f"\n  {BOLD}Options:{RESET}")
            print(f"    {CYN}[A]{RESET} Auto-install now")
            print(f"    {CYN}[S]{RESET} Skip and continue anyway")
            print(f"    {CYN}[Q]{RESET} Quit")
            try:
                choice = input(f"\n  Choice [A/s/q]: ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                choice = 's'
            if choice in ('', 'a'):
                ok = auto_install(to_install)
                if ok:
                    print(f"\n  {GRN}Packages installed. Continuing…{RESET}")
                    all_ok = True
                else:
                    print(f"\n  {RED}Installation failed.{RESET}")
                    all_ok = False
            elif choice == 'q':
                print("  Exiting.")
                sys.exit(1)
            else:
                print(f"  {YEL}Skipping. Some features may not work.{RESET}")

    # ── System install hints
    if missing_system:
        print(f"\n  {BOLD}To enable OCR for scanned PDFs, install:{RESET}")
        for dep in missing_system:
            plat = sys.platform if sys.platform in dep["install"] else "linux"
            print(f"\n    {YEL}{dep['name']}{RESET}")
            for line in dep["install"][plat].splitlines():
                print(f"      {line}")

    # ── Summary
    print()
    if all_ok and not missing_system:
        print(f"  {GRN}{BOLD}All dependencies satisfied.{RESET}\n")
    elif all_ok:
        print(f"  {YEL}{BOLD}Core deps OK — OCR on scanned PDFs limited (see above).{RESET}\n")
    else:
        print(f"  {RED}{BOLD}Some dependencies missing. App may not function correctly.{RESET}\n")

    print(f"{BOLD}{'─'*54}{RESET}\n")
    return all_ok
