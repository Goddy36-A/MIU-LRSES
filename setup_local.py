#!/usr/bin/env python3
"""One-time local setup for MIU-LRSES. Standard library only.

What it does (safe to run again; finished steps are skipped):
  1. checks your Python version
  2. creates a private virtual environment in ./venv
  3. installs the requirements
  4. creates/updates the database (migrations)
  5. creates your administrator account (asks you; typing the password is hidden)

Normally you do not run this directly: double-click start.bat (Windows) or run ./start.sh.
"""
import argparse
import getpass
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / "venv"
IS_WIN = os.name == "nt"
VPY = VENV / ("Scripts/python.exe" if IS_WIN else "bin/python")
MARKER = ROOT / ".setup_done"
MIN_PY = (3, 10)
TOTAL = 5

CREATE_ADMIN = '''
import os, sys
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
U = get_user_model()
u, e, p = os.environ["MIU_U"], os.environ["MIU_E"], os.environ["MIU_P"]
if U.objects.filter(username__iexact=u).exists():
    print("That username is already taken."); sys.exit(2)
try:
    validate_password(p, U(username=u, email=e))
except ValidationError as exc:
    print(" ".join(exc.messages)); sys.exit(3)
U.objects.create_superuser(u, e, p)
'''
HAS_ADMIN = ("from django.contrib.auth import get_user_model as g; import sys; "
             "sys.exit(0 if g().objects.filter(is_superuser=True).exists() else 1)")


def say(msg=""):
    print(msg, flush=True)


def step(n, msg):
    say(f"\n[{n}/{TOTAL}] {msg}")


def fail(msg, code=1):
    say(f"\nERROR: {msg}")
    sys.exit(code)


def run(cmd, **kw):
    return subprocess.run([str(c) for c in cmd], cwd=ROOT, **kw)


def manage(*args, **kw):
    return run([VPY, "manage.py", *args], **kw)


def ask(prompt, default=""):
    suffix = f" [{default}]" if default else ""
    value = input(f"{prompt}{suffix}: ").strip()
    return value or default


def ask_secret(prompt):
    return getpass.getpass(f"{prompt} (typing is hidden): ")


def has_admin():
    return manage("shell", "-c", HAS_ADMIN, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


def create_admin(username, email, password):
    env = dict(os.environ, MIU_U=username, MIU_E=email, MIU_P=password)
    result = manage("shell", "-c", CREATE_ADMIN, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result.returncode == 0:
        return True, ""
    message = result.stdout.strip().splitlines()
    return False, (message[-1] if message and result.returncode in (2, 3) else (result.stderr.strip()[-300:] or "unknown error"))


def main():
    p = argparse.ArgumentParser(description="One-time local setup for MIU-LRSES.")
    p.add_argument("--admin-user")
    p.add_argument("--admin-email", default="")
    p.add_argument("--admin-password")
    p.add_argument("--no-prompt", action="store_true", help="never ask questions (for automation)")
    args = p.parse_args()
    interactive = not args.no_prompt and sys.stdin.isatty()

    say("=" * 60)
    say(" MIU-LRSES local setup (this can take a few minutes the first time)")
    say("=" * 60)

    step(1, "Checking Python")
    if sys.version_info < MIN_PY:
        fail(f"Python {MIN_PY[0]}.{MIN_PY[1]} or newer is required; you have {sys.version.split()[0]}.\n"
             "Install the latest Python from https://www.python.org/downloads/ and tick 'Add python.exe to PATH'.")
    say(f"Python {sys.version.split()[0]} - OK")

    step(2, "Creating the private Python environment (venv)")
    if VPY.exists():
        say("Already exists - skipped.")
    else:
        if run([sys.executable, "-m", "venv", VENV]).returncode != 0 or not VPY.exists():
            fail("Could not create the virtual environment. On Ubuntu/Debian run: sudo apt install python3-venv")
        say("Created.")

    step(3, "Installing the required packages (needs internet the first time)")
    if run([VPY, "-m", "pip", "install", "--disable-pip-version-check", "-r", "requirements.txt"]).returncode != 0:
        fail("Package installation failed. Check your internet connection and run this again.")

    step(4, "Preparing the database")
    if manage("migrate", "--noinput", stdout=subprocess.DEVNULL).returncode != 0:
        manage("migrate", "--noinput")  # show the real error
        fail("Database setup failed (see the message above).")
    say("Database ready.")
    if manage("load_institution_data", stdout=subprocess.DEVNULL).returncode == 0:
        say("University programmes and the research study profile are loaded.")
    else:
        say("Note: the university programmes could not be loaded automatically. You can add them later with: python manage.py load_institution_data")

    step(5, "Administrator account")
    admin_name = None
    if has_admin():
        say("An administrator already exists - skipped.")
    else:
        username, email, password = args.admin_user, args.admin_email, args.admin_password
        if username and password:
            ok, why = create_admin(username, email, password)
            if not ok:
                fail(f"Could not create the administrator: {why}")
            admin_name = username
        elif interactive:
            say("Create the account you will use to sign in as system administrator.")
            for attempt in range(1, 4):
                username = ask("Username", "admin")
                email = ask("Email (optional)")
                password = ask_secret("Password")
                if password != ask_secret("Repeat password"):
                    say("The two passwords did not match. Try again.")
                    continue
                ok, why = create_admin(username, email, password)
                if ok:
                    admin_name = username
                    break
                say(f"Not accepted: {why} (attempt {attempt} of 3)")
            if not admin_name:
                fail("No administrator was created. Run setup again, or create one later with:\n"
                     f"  {VPY} manage.py createsuperuser")
        else:
            say("Skipped (no questions allowed). Create one later with:\n"
                f"  {VPY} manage.py createsuperuser")
    if admin_name:
        say(f"Administrator '{admin_name}' created.")

    # Only mark setup as finished when someone can actually sign in; otherwise start.bat will ask again.
    finished = has_admin()
    if finished:
        MARKER.write_text("MIU-LRSES local setup completed.\n")
    elif MARKER.exists():
        MARKER.unlink()
    say("\n" + "=" * 60)
    say(" SETUP COMPLETE" if finished else " SETUP INCOMPLETE - no administrator account exists yet")
    say("=" * 60)
    if not finished:
        say(" Run setup again (double-click start.bat) and create the administrator account.")
        say("=" * 60)
        return 1
    say(" Start the system:  double-click start.bat (Windows) or run ./start.sh")
    say(" Then open:         http://127.0.0.1:8000/")
    say("=" * 60)


if __name__ == "__main__":
    try:
        sys.exit(main() or 0)
    except KeyboardInterrupt:
        fail("Cancelled.", 130)
