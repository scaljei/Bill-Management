"""
deps.py — Dependency checker for BillVault.
Runs at startup, checks Python packages and system binaries,
prints a clear report and prompts to auto-install missing Python packages.
"""

import sys
import os
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


# ── Git version check ────────────────────────────────────────────────────────

def check_git_version() -> dict:
    """
    Check local vs remote git state.
    Returns dict with keys:
      git_available, in_repo, local_sha, remote_sha,
      commits_behind, commits_ahead, branch, remote_url,
      status (ok | behind | ahead | diverged | no_remote | no_git | error),
      error_msg
    """
    result = {
        "git_available": False, "in_repo": False,
        "local_sha": None, "remote_sha": None,
        "commits_behind": 0, "commits_ahead": 0,
        "branch": None, "remote_url": None,
        "status": "no_git", "error_msg": None,
    }

    if not shutil.which("git"):
        return result
    result["git_available"] = True

    def _git(*args, cwd=None):
        r = subprocess.run(
            ["git"] + list(args),
            capture_output=True, text=True, timeout=10,
            cwd=cwd or os.path.dirname(os.path.abspath(__file__))
        )
        return r.stdout.strip(), r.stderr.strip(), r.returncode

    # Are we inside a repo?
    _, _, rc = _git("rev-parse", "--git-dir")
    if rc != 0:
        result["status"] = "no_git"
        return result
    result["in_repo"] = True

    # Current branch
    branch, _, _ = _git("rev-parse", "--abbrev-ref", "HEAD")
    result["branch"] = branch or "HEAD"

    # Local SHA
    local_sha, _, _ = _git("rev-parse", "HEAD")
    result["local_sha"] = local_sha[:7] if local_sha else None

    # Remote URL
    remote_url, _, rc = _git("remote", "get-url", "origin")
    if rc != 0:
        result["status"] = "no_remote"
        result["error_msg"] = "No remote 'origin' configured"
        return result
    result["remote_url"] = remote_url

    # Fetch quietly (timeout generous for slow connections)
    _, fetch_err, fetch_rc = _git("fetch", "origin", "--quiet")
    if fetch_rc != 0:
        result["status"] = "error"
        result["error_msg"] = f"fetch failed: {fetch_err[:120]}"
        return result

    # Remote SHA
    remote_sha, _, _ = _git("rev-parse", f"origin/{branch}")
    result["remote_sha"] = remote_sha[:7] if remote_sha else None

    # Counts
    behind_str, _, _ = _git("rev-list", "--count", f"HEAD..origin/{branch}")
    ahead_str,  _, _ = _git("rev-list", "--count", f"origin/{branch}..HEAD")
    try:
        result["commits_behind"] = int(behind_str)
        result["commits_ahead"]  = int(ahead_str)
    except ValueError:
        pass

    behind = result["commits_behind"]
    ahead  = result["commits_ahead"]

    if behind == 0 and ahead == 0:
        result["status"] = "ok"
    elif behind > 0 and ahead == 0:
        result["status"] = "behind"
    elif ahead > 0 and behind == 0:
        result["status"] = "ahead"
    else:
        result["status"] = "diverged"

    return result


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

    # ── Git version check
    print(f"\n  {BOLD}Git version{RESET}")
    gv = check_git_version()
    if not gv["git_available"]:
        print(f"    {WARN} git not found — skipping update check")
    elif not gv["in_repo"]:
        print(f"    {WARN} Not inside a git repository")
    elif gv["status"] == "no_remote":
        print(f"    {WARN} No remote origin configured")
    elif gv["status"] == "error":
        print(f"    {WARN} Could not reach remote  {DIM}({gv['error_msg']}){RESET}")
    elif gv["status"] == "ok":
        if not quiet:
            print(f"    {OK} Up to date  {DIM}({gv['branch']} @ {gv['local_sha']}){RESET}")
    elif gv["status"] == "behind":
        n = gv["commits_behind"]
        print(f"    {WARN} {YEL}{n} commit{'s' if n!=1 else ''} behind origin/{gv['branch']}{RESET}  "
              f"{DIM}(local {gv['local_sha']} → remote {gv['remote_sha']}){RESET}")
        print(f"\n    {BOLD}Run to update:{RESET}")
        print(f"      {CYN}git pull{RESET}")
        print()
        try:
            choice = input(f"  Pull now? [Y/n]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            choice = 'n'
        if choice in ('', 'y'):
            print()
            pull_result = subprocess.run(["git", "pull"], cwd=os.path.dirname(os.path.abspath(__file__)))
            if pull_result.returncode == 0:
                print(f"\n  {GRN}Pull successful. Restart the app to apply updates.{RESET}")
                sys.exit(0)
            else:
                print(f"\n  {RED}Pull failed. Please run 'git pull' manually.{RESET}")
        else:
            print(f"  {YEL}Skipping update.{RESET}")
    elif gv["status"] == "ahead":
        n = gv["commits_ahead"]
        if not quiet:
            print(f"    {CYN}{n} local commit{'s' if n!=1 else ''} ahead of origin{RESET}  "
                  f"{DIM}({gv['branch']} @ {gv['local_sha']}){RESET}")
    elif gv["status"] == "diverged":
        print(f"    {WARN} Branch has diverged from origin/{gv['branch']}  "
              f"{DIM}({gv['commits_behind']} behind, {gv['commits_ahead']} ahead){RESET}")

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
