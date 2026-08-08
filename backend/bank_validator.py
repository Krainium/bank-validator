#!/usr/bin/env python3
"""
Bank Account Validator & Monitor  (NG)
made by Krainium

Backend (pluggable — first key found wins):
  Priority 1 — Paystack   (PAYSTACK_SECRET_KEY / PAYSTACK_KEY)
  Priority 2 — NubAPI     (auto-acquired; no key needed)

Stdlib only — no pip installs needed.
"""

import os
import sys
import json
import time
import random
import string
import argparse
import re
import subprocess
import shutil
import http.cookiejar
import urllib.parse
import urllib.request
import urllib.error
from pathlib import Path

# --------------------------------------------------------------------------- #
#  Colors
# --------------------------------------------------------------------------- #
class C:
    _on = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None
    RESET   = "\033[0m"  if _on else ""
    BOLD    = "\033[1m"  if _on else ""
    DIM     = "\033[2m"  if _on else ""
    RED     = "\033[91m" if _on else ""
    GREEN   = "\033[92m" if _on else ""
    YELLOW  = "\033[93m" if _on else ""
    BLUE    = "\033[94m" if _on else ""
    MAGENTA = "\033[95m" if _on else ""
    CYAN    = "\033[96m" if _on else ""
    WHITE   = "\033[97m" if _on else ""
    GREY    = "\033[90m" if _on else ""

def c(text, color):
    return f"{color}{text}{C.RESET}"

# --------------------------------------------------------------------------- #
#  Banner
# --------------------------------------------------------------------------- #
BANNER = r"""
 ____              _      _                             _
| __ )  __ _ _ __ | | __ / \   ___ ___ ___  _   _ _ __ | |_
|  _ \ / _` | '_ \| |/ // _ \ / __/ __/ _ \| | | | '_ \| __|
| |_) | (_| | | | |   </ ___ \ (_| (_| (_) | |_| | | | | |_
|____/ \__,_|_| |_|_|\_/_/   \_\___\___\___/ \__,_|_| |_|\__|
   __     __    _ _     _       _
   \ \   / /_ _| (_) __| | __ _| |_ ___  _ __
    \ \ / / _` | | |/ _` |/ _` | __/ _ \| '__|
     \ V / (_| | | | (_| | (_| | || (_) | |
      \_/ \__,_|_|_|\__,_|\__,_|\__\___/|_|   &  MONITOR
"""

def banner():
    print(c(BANNER, C.CYAN + C.BOLD))
    line = "═" * 62
    print(c("  " + line, C.BLUE))
    print("  " + c("Bank Account Validator", C.GREEN + C.BOLD) +
          c("  &  ", C.GREY) +
          c("Monitor", C.YELLOW + C.BOLD) +
          c("   [ NG ]", C.MAGENTA + C.BOLD))
    print("  " + c("made by ", C.GREY) + c("Krainium", C.MAGENTA + C.BOLD))
    print(c("  " + line, C.BLUE))
    print()

# --------------------------------------------------------------------------- #
#  Provider error
# --------------------------------------------------------------------------- #
class ProviderError(Exception):
    pass

# --------------------------------------------------------------------------- #
#  Config / key store
# --------------------------------------------------------------------------- #
_CONFIG_DIR   = Path.home() / ".config" / "bank_validator"
_CONFIG_FILE  = _CONFIG_DIR / "config.json"
_TOKEN_CACHE  = _CONFIG_DIR / "nubapi_token"


def _load_config():
    try:
        if _CONFIG_FILE.exists():
            return json.loads(_CONFIG_FILE.read_text())
    except Exception:
        pass
    return {}


def _save_config(cfg):
    try:
        _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        _CONFIG_FILE.write_text(json.dumps(cfg, indent=2))
    except Exception:
        pass


def _clear_saved_key():
    cfg = _load_config()
    cfg.pop("provider", None)
    cfg.pop("key", None)
    _save_config(cfg)
    if _TOKEN_CACHE.exists():
        _TOKEN_CACHE.unlink()

def _load_cached_token():
    try:
        if _TOKEN_CACHE.exists():
            tok = _TOKEN_CACHE.read_text().strip()
            if tok:
                return tok
    except Exception:
        pass
    return None

def _save_token(tok):
    try:
        _TOKEN_CACHE.parent.mkdir(parents=True, exist_ok=True)
        _TOKEN_CACHE.write_text(tok)
    except Exception:
        pass

# --------------------------------------------------------------------------- #
#  NubAPI auto-token acquisition
#
#  Strategy A — public defaultApiToken:
#    GET https://nubapi.com/register returns an Inertia page that always
#    includes a defaultApiToken in the page props.  No login required.
# --------------------------------------------------------------------------- #
NUBAPI_BASE   = "https://nubapi.com"
MAILINATOR_BASE = "https://api.mailinator.com/api/v2"

def _inertia_props(html):
    """Parse Inertia data-page JSON from raw HTML."""
    m = re.search(r'data-page="(.*?)"', html, re.DOTALL)
    if not m:
        return {}
    try:
        return json.loads(m.group(1).replace("&quot;", '"').replace("&#039;", "'"))
    except Exception:
        return {}

def _fetch_default_token():
    """Fetch the public defaultApiToken exposed on the NubAPI register page."""
    try:
        req = urllib.request.Request(
            NUBAPI_BASE + "/register",
            headers={"Accept": "text/html", "User-Agent": "Mozilla/5.0 Chrome/124"},
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            html = r.read().decode("utf-8", "replace")
        page = _inertia_props(html)
        tok = page.get("props", {}).get("defaultApiToken", "")
        return tok or None
    except Exception:
        return None

def _register_mailinator():
    """
    Auto-register on NubAPI using a Mailinator throwaway address.
    Returns the personal bearer token string, or None on failure.
    """
    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(cj),
        urllib.request.HTTPRedirectHandler(),
    )

    def get_cookie(name):
        for ck in cj:
            if ck.name == name:
                return urllib.parse.unquote(ck.value)
        return ""

    def do(url, method="GET", data=None, extra=None):
        headers = {
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*",
            "User-Agent": "Mozilla/5.0 Chrome/124",
        }
        if extra:
            headers.update(extra)
        if data is not None:
            data = json.dumps(data).encode()
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            resp = opener.open(req, timeout=20)
            return resp.status, resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8", "replace")
        except Exception:
            return 0, ""

    try:
        # 1. GET /register
        status, html = do(NUBAPI_BASE + "/register")
        if status != 200:
            return None
        page = _inertia_props(html)
        version = page.get("version", "")
        xsrf = get_cookie("XSRF-TOKEN")
        if not xsrf or not version:
            return None

        # 2. POST /register with fresh Mailinator address
        rand = "".join(random.choices(string.ascii_lowercase + string.digits, k=10))
        email = f"krainium{rand}@mailinator.com"
        pwd = "".join(random.choices(string.ascii_letters + string.digits + "!@#$", k=16))

        status, body = do(
            NUBAPI_BASE + "/register",
            method="POST",
            data={"name": "Krainium", "email": email,
                  "password": pwd, "password_confirmation": pwd},
            extra={
                "X-XSRF-TOKEN": xsrf,
                "X-Inertia": "true",
                "X-Inertia-Version": version,
                "Referer": NUBAPI_BASE + "/register",
                "Accept": "application/json",
            },
        )
        if status not in (200, 302):
            return None

        # 3. POST /user/api-tokens to create a named personal token
        time.sleep(0.3)
        xsrf2 = get_cookie("XSRF-TOKEN")

        status, body = do(
            NUBAPI_BASE + "/user/api-tokens",
            method="POST",
            data={"name": "BankValidator"},
            extra={
                "X-XSRF-TOKEN": xsrf2,
                "X-Inertia": "true",
                "X-Inertia-Version": version,
                "Referer": NUBAPI_BASE + "/dashboard",
                "Accept": "application/json",
            },
        )
        if status != 200:
            return None

        tok_data = json.loads(body) if body.startswith("{") else {}
        token = tok_data.get("props", {}).get("flash", {}).get("token", "")
        return token or None

    except Exception:
        return None

def acquire_token(verbose=False):
    """
    Return a working NubAPI bearer token using the best available method.
    Priority: env var → cached token → public defaultApiToken → mailinator auto-register
    """
    # 0. Explicit override
    env_tok = os.environ.get("NUBAPI_TOKEN", "").strip()
    if env_tok:
        return env_tok

    # 1. Cached token from a previous run
    cached = _load_cached_token()
    if cached:
        return cached

    # 2. Public defaultApiToken (no registration required)
    if verbose:
        sys.stdout.write("  " + c("» ", C.YELLOW) + "Fetching public NubAPI token... ")
        sys.stdout.flush()
    tok = _fetch_default_token()
    if tok:
        if verbose:
            print(c("OK", C.GREEN + C.BOLD))
        _save_token(tok)
        return tok
    if verbose:
        print(c("not available", C.GREY))

    # 3. Mailinator auto-register
    if verbose:
        sys.stdout.write("  " + c("» ", C.YELLOW) + "Auto-registering via Mailinator... ")
        sys.stdout.flush()
    tok = _register_mailinator()
    if tok:
        if verbose:
            print(c("OK", C.GREEN + C.BOLD))
        _save_token(tok)
        return tok
    if verbose:
        print(c("FAILED", C.RED))

    return None

# --------------------------------------------------------------------------- #
#  NubAPI provider
# --------------------------------------------------------------------------- #
class NubApiProvider:
    """
    Uses NubAPI (nubapi.com) for Nigerian bank account validation.
    Token is acquired automatically — no manual setup required.
    """
    BASE = NUBAPI_BASE
    name = "NubAPI (auto)"

    def __init__(self, token):
        if not token:
            raise ProviderError(
                "Could not acquire a NubAPI token automatically.\n"
                "Set one manually:  export NUBAPI_TOKEN=\"your_token\"\n"
                "Get one free at:   nubapi.com"
            )
        self.token = token

    def _get(self, path, params=None, auth=True):
        url = self.BASE + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        headers = {
            "Accept": "application/json",
            "User-Agent": "Krainium-BankValidator/2.0",
        }
        if auth:
            headers["Authorization"] = f"Bearer {self.token}"
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=25) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")
            try:
                msg = json.loads(body).get("message", body)
            except Exception:
                msg = body
            raise ProviderError(f"HTTP {e.code}: {msg}")
        except urllib.error.URLError as e:
            raise ProviderError(f"Network error: {e.reason}")

    def list_banks(self):
        """
        Uses NubAPI's public (no-auth) /bank-json endpoint.
        Returns 707+ active Nigerian banks.
        """
        try:
            data = self._get("/bank-json", auth=False)
            if isinstance(data, list):
                return [
                    {
                        "name": b.get("name"),
                        "code": b.get("code"),
                        "active": bool(b.get("active", True)),
                        "type": b.get("type", "nuban"),
                    }
                    for b in data if b.get("code")
                ]
        except ProviderError:
            pass
        # Fallback: public /banks returns {code: name} dict
        try:
            data = self._get("/banks", auth=False)
            if isinstance(data, dict):
                return [{"name": v, "code": k, "active": True, "type": ""}
                        for k, v in data.items()]
        except ProviderError:
            pass
        return []

    def resolve(self, account_number, bank_code):
        """Return account holder name or None."""
        try:
            resp = self._get("/api/verify", {
                "account_number": account_number,
                "bank_code": bank_code,
            })
        except ProviderError:
            return None
        status = resp.get("status")
        if status is True or str(status).lower() == "true":
            return resp.get("account_name") or resp.get("account_name")
        return None


# --------------------------------------------------------------------------- #
#  Paystack provider
# --------------------------------------------------------------------------- #
def _curl_get(url, headers=None):
    """
    HTTP GET via curl subprocess — bypasses Cloudflare's Python TLS fingerprint ban.
    Returns parsed JSON dict, or raises ProviderError.
    """
    if not shutil.which("curl"):
        raise ProviderError("curl not found; install curl and retry")
    cmd = ["curl", "-s", "--max-time", "25", url]
    for k, v in (headers or {}).items():
        cmd += ["-H", f"{k}: {v}"]
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=30)
        body = result.stdout.decode("utf-8", "replace").strip()
        if not body:
            raise ProviderError("Empty response from server")
        return json.loads(body)
    except subprocess.TimeoutExpired:
        raise ProviderError("Request timed out")
    except json.JSONDecodeError as e:
        raise ProviderError(f"Bad JSON: {e}")


class PaystackProvider:
    """Uses Paystack (paystack.com) for Nigerian bank account validation."""
    BASE = "https://api.paystack.co"
    name = "Paystack"

    def __init__(self, key):
        self.key = key

    def _req(self, path, params=None):
        url = self.BASE + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        return _curl_get(url, {"Authorization": f"Bearer {self.key}"})

    def list_banks(self):
        data = self._req("/bank", {"country": "nigeria", "perPage": "200"})
        banks = data.get("data", [])
        page = 1
        while data.get("meta", {}).get("next"):
            page += 1
            data = self._req("/bank", {"country": "nigeria", "perPage": "200", "page": page})
            banks += data.get("data", [])
        return [
            {"name": b.get("name"), "code": b.get("code"),
             "active": b.get("active", True), "type": b.get("type", "nuban")}
            for b in banks if b.get("code")
        ]

    def resolve(self, account_number, bank_code):
        try:
            resp = self._req("/bank/resolve", {
                "account_number": account_number,
                "bank_code": bank_code,
            })
        except ProviderError:
            return None
        if resp.get("status"):
            return resp.get("data", {}).get("account_name")
        return None


def build_provider(verbose=False):
    # Priority 1: env var (always wins)
    ps_key = os.environ.get("PAYSTACK_SECRET_KEY") or os.environ.get("PAYSTACK_KEY")
    if ps_key:
        return PaystackProvider(ps_key)
    nub_env = os.environ.get("NUBAPI_TOKEN", "").strip()
    if nub_env:
        return NubApiProvider(nub_env)

    # Priority 2: saved config file
    cfg = _load_config()
    if cfg.get("provider") == "paystack" and cfg.get("key"):
        return PaystackProvider(cfg["key"])
    if cfg.get("provider") == "nubapi" and cfg.get("key"):
        return NubApiProvider(cfg["key"])

    # Priority 3: NubAPI auto-acquired token
    token = acquire_token(verbose=verbose)
    return NubApiProvider(token)


def _validate_key(provider_name, key):
    """
    Quick smoke-test that a key actually works.
    Returns (True, info_str) or (False, error_str).
    """
    try:
        if provider_name == "paystack":
            p = PaystackProvider(key)
            # Try a lightweight endpoint
            data = p._req("/bank", {"country": "nigeria", "perPage": "1"})
            if data.get("status"):
                return True, "Paystack — key accepted"
            return False, data.get("message", "Rejected by Paystack")
        elif provider_name == "nubapi":
            p = NubApiProvider(key)
            banks = p.list_banks()
            if banks:
                return True, f"NubAPI — bank list OK ({len(banks)} banks)"
            return False, "NubAPI returned empty bank list"
    except ProviderError as e:
        return False, str(e)
    except Exception as e:
        return False, str(e)
    return False, "Unknown error"


def manage_api_key():
    """Interactive menu for setting / clearing the saved API key."""
    print()
    print("  " + c("┌─ API Key Manager ", C.YELLOW + C.BOLD) + c("─" * 43, C.YELLOW))

    cfg = _load_config()
    current = cfg.get("provider")
    if current:
        print("  " + c("│ ", C.YELLOW) + "Current: " +
              c(f"{current.title()} key saved", C.GREEN + C.BOLD))
    else:
        print("  " + c("│ ", C.YELLOW) + c("No key saved — using auto-acquired NubAPI token", C.GREY))
    print("  " + c("└" + "─" * 60, C.YELLOW))
    print()
    print("    " + c("[1]", C.CYAN + C.BOLD) + " Set Paystack secret key   " +
          c("(sk_live_... / sk_test_...)", C.GREY))
    print("    " + c("[2]", C.CYAN + C.BOLD) + " Set NubAPI token          " +
          c("(get free at nubapi.com)", C.GREY))
    print("    " + c("[3]", C.RED  + C.BOLD) + " Clear saved key           " +
          c("(revert to auto NubAPI)", C.GREY))
    print("    " + c("[0]", C.GREY) + " Back")
    print()

    try:
        choice = input("  " + c("krainium➤ ", C.MAGENTA + C.BOLD)).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return None

    if choice == "0":
        return None

    if choice == "3":
        _clear_saved_key()
        print()
        print("  " + c("✓ Saved key cleared. Auto-NubAPI will be used.", C.GREEN))
        print()
        return "rebuild"

    if choice not in ("1", "2"):
        print("  " + c("Invalid option.\n", C.RED))
        return None

    pname = "paystack" if choice == "1" else "nubapi"
    hint  = "sk_live_... or sk_test_..." if pname == "paystack" else "your NubAPI bearer token"
    print()

    try:
        key = input("  " + c(f"Enter {pname.title()} key ({hint}): ", C.CYAN)).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return None

    if not key:
        print("  " + c("No key entered.\n", C.RED))
        return None

    sys.stdout.write("  " + c("» ", C.YELLOW) + "Validating key... ")
    sys.stdout.flush()
    ok, msg = _validate_key(pname, key)
    if ok:
        print(c("OK", C.GREEN + C.BOLD))
        print("  " + c(f"  {msg}", C.GREY))
        cfg["provider"] = pname
        cfg["key"]      = key
        _save_config(cfg)
        print("  " + c("✓ Key saved to ~/.config/bank_validator/config.json", C.GREEN))
        print()
        return "rebuild"
    else:
        print(c("FAILED", C.RED + C.BOLD))
        print("  " + c(f"  {msg}", C.RED))
        print()
        return None

# --------------------------------------------------------------------------- #
#  Common Nigerian fintech / bank codes (priority scan order)
# --------------------------------------------------------------------------- #
PRIORITY_CODES = [
    ("999992", "OPay"),
    ("999991", "PalmPay"),
    ("50515",  "Moniepoint MFB"),
    ("50211",  "Kuda"),
    ("100004", "OPay Digital"),
    ("120001", "9PSB"),
    ("090267", "Kuda (alt)"),
    ("044",    "Access Bank"),
    ("058",    "GTBank"),
    ("057",    "Zenith Bank"),
    ("011",    "First Bank"),
    ("033",    "UBA"),
    ("214",    "FCMB"),
    ("070",    "Fidelity Bank"),
    ("232",    "Sterling Bank"),
    ("076",    "Polaris Bank"),
    ("082",    "Keystone Bank"),
    ("032",    "Union Bank"),
    ("221",    "Stanbic IBTC"),
    ("035",    "Wema Bank"),
    ("050",    "Ecobank"),
]

# --------------------------------------------------------------------------- #
#  Features
# --------------------------------------------------------------------------- #
def spinner(msg):
    sys.stdout.write("  " + c("» ", C.YELLOW) + msg + " ")
    sys.stdout.flush()


def validate_account(provider, account_number, bank_code=None, bank_name=None,
                     auto_scan=True):
    print()
    print("  " + c("┌─ Account Validation ", C.CYAN + C.BOLD) +
          c("─" * 40, C.CYAN))
    print("  " + c("│ ", C.CYAN) + "Account : " + c(account_number, C.WHITE + C.BOLD))
    if bank_name or bank_code:
        print("  " + c("│ ", C.CYAN) + "Bank    : " +
              c(bank_name or bank_code, C.WHITE))
    print("  " + c("└" + "─" * 60, C.CYAN))
    print()

    if bank_code:
        spinner(f"Resolving against {bank_name or bank_code}...")
        name = provider.resolve(account_number, bank_code)
        if name:
            print(c("OK", C.GREEN + C.BOLD))
            _print_result(bank_name or bank_code, account_number, name)
            return True
        print(c("not found on this bank", C.YELLOW))
        return False

    if not auto_scan:
        print("  " + c("No bank code supplied.", C.YELLOW))
        return False

    print("  " + c("No bank supplied — scanning banks for a match...", C.GREY))
    print()

    # Build scan list: priority codes first, then rest of the 707-bank list
    scan = list(PRIORITY_CODES)
    try:
        seen = {code for code, _ in scan}
        for b in provider.list_banks():
            if b["code"] and b["code"] not in seen and b["active"]:
                scan.append((b["code"], b["name"]))
                seen.add(b["code"])
    except ProviderError as e:
        print("  " + c(f"(could not load full bank list: {e})", C.GREY))

    for i, (code, bname) in enumerate(scan, 1):
        spinner(f"[{i:>3}/{len(scan)}] {bname:<28.28}")
        name = provider.resolve(account_number, code)
        if name:
            print(c("MATCH", C.GREEN + C.BOLD))
            _print_result(bname, account_number, name)
            return True
        print(c("·", C.GREY))
        # Paystack has no rate-limit on /bank/resolve; NubAPI needs a small delay
        if provider.name != "Paystack":
            time.sleep(0.10)

    print()
    print("  " + c("✗ Account not found on any scanned bank.", C.RED + C.BOLD))
    return False


def _row(label, value, value_color, width=58):
    plain = f"  {label} : {value}"
    pad = " " * max(0, width - len(plain))
    colored = f"  {label} : {c(value, value_color)}"
    return "  " + c("║", C.GREEN) + colored + pad + c("║", C.GREEN)


def _print_result(bank_name, account_number, account_name):
    print()
    print("  " + c("╔" + "═" * 58 + "╗", C.GREEN))
    title = "  ✓  VALID ACCOUNT"
    print("  " + c("║", C.GREEN) + c(title, C.GREEN + C.BOLD) +
          " " * (58 - len(title)) + c("║", C.GREEN))
    print("  " + c("╠" + "═" * 58 + "╣", C.GREEN))
    print(_row("Bank Name   ", bank_name, C.CYAN + C.BOLD))
    print(_row("Account No  ", account_number, C.WHITE + C.BOLD))
    print(_row("Account Name", account_name, C.YELLOW + C.BOLD))
    print("  " + c("╚" + "═" * 58 + "╝", C.GREEN))
    print()


def monitor_banks(provider, only_active=False):
    print()
    print("  " + c("┌─ Bank Network Monitor ", C.CYAN + C.BOLD) + c("─" * 38, C.CYAN))
    print("  " + c("└" + "─" * 60, C.CYAN))
    spinner("Fetching bank directory...")
    try:
        banks = provider.list_banks()
    except ProviderError as e:
        print(c("FAILED", C.RED))
        print("  " + c(str(e), C.RED))
        return
    print(c("done", C.GREEN) + c(f"  ({len(banks)} banks)", C.GREY))
    print()

    active = [b for b in banks if b["active"]]
    inactive = [b for b in banks if not b["active"]]
    show = active if only_active else banks

    header = f"  {'#':>3}  {'STATUS':<10}{'CODE':<10}BANK"
    print(c(header, C.BOLD + C.WHITE))
    print(c("  " + "─" * 60, C.GREY))
    for i, b in enumerate(sorted(show, key=lambda x: (not x["active"], x["name"] or "")), 1):
        dot = c("● ONLINE ", C.GREEN + C.BOLD) if b["active"] else c("● OFFLINE", C.RED + C.BOLD)
        idx = c(f"{i:>3}", C.GREY)
        code = c(f"{(b['code'] or '-'):<8}", C.CYAN)
        print(f"  {idx}  {dot}  {code}  {b['name']}")

    print(c("  " + "─" * 60, C.GREY))
    print("  " + c(f"Total: {len(banks)}", C.WHITE) +
          c(f"   ● Active: {len(active)}", C.GREEN) +
          c(f"   ● Down: {len(inactive)}", C.RED))
    print()


# --------------------------------------------------------------------------- #
#  Card network (BIN) lookup  +  Card network monitor database
# --------------------------------------------------------------------------- #

# Verve BIN prefixes — Nigerian card scheme by Interswitch.
# binlist.net doesn't always classify these correctly, so we detect locally first.
_VERVE_PREFIXES = (
    "5061", "6500", "6272", "5078",
    "650002", "650003", "650004", "650005",
    "507080", "507081", "507082", "507099",
)

_NETWORK_COLORS = {
    "visa":       C.BLUE + C.BOLD,
    "mastercard": C.RED  + C.BOLD,
    "verve":      C.GREEN + C.BOLD,
    "unknown":    C.GREY,
}

# Nigerian bank → card network support matrix
# Each entry: (bank_name, paystack_code, [networks...])
# Networks: "visa", "mastercard", "verve"
CARD_NETWORK_DB = [
    # ── Tier-1 commercial banks ──────────────────────────────────────────────
    ("Access Bank",             "044",     ["visa", "mastercard", "verve"]),
    ("Citibank Nigeria",        "023",     ["visa", "mastercard"]),
    ("Ecobank Nigeria",         "050",     ["visa", "mastercard", "verve"]),
    ("Fidelity Bank",           "070",     ["visa", "mastercard", "verve"]),
    ("First Bank of Nigeria",   "011",     ["visa", "mastercard", "verve"]),
    ("FCMB",                    "214",     ["visa", "mastercard", "verve"]),
    ("Guaranty Trust Bank",     "058",     ["visa", "mastercard", "verve"]),
    ("Keystone Bank",           "082",     ["visa", "mastercard", "verve"]),
    ("Polaris Bank",            "076",     ["visa", "mastercard", "verve"]),
    ("Stanbic IBTC Bank",       "221",     ["visa", "mastercard", "verve"]),
    ("Standard Chartered",      "068",     ["visa", "mastercard"]),
    ("Sterling Bank",           "232",     ["visa", "mastercard", "verve"]),
    ("UBA",                     "033",     ["visa", "mastercard", "verve"]),
    ("Union Bank",              "032",     ["visa", "mastercard", "verve"]),
    ("Unity Bank",              "215",     ["visa", "verve"]),
    ("Wema Bank",               "035",     ["visa", "mastercard", "verve"]),
    ("Zenith Bank",             "057",     ["visa", "mastercard", "verve"]),
    # ── Tier-2 / mid-size commercial banks ───────────────────────────────────
    ("Alpha Morgan Bank",       "108",     ["visa", "verve"]),
    ("Alternative Bank",        "000304",  ["mastercard", "verve"]),
    ("Coronation Merchant Bank","559",     ["visa"]),
    ("FSDH Merchant Bank",      "501",     ["visa"]),
    ("Globus Bank",             "00103",   ["visa", "verve"]),
    ("Greenwich Merchant Bank", "562",     ["visa"]),
    ("Heritage Bank",           "030",     ["visa", "verve"]),
    ("Jaiz Bank",               "301",     ["visa", "mastercard", "verve"]),
    ("Lotus Bank",              "303",     ["visa", "mastercard", "verve"]),
    ("Nova Bank",               "561",     ["visa", "verve"]),
    ("Optimus Bank",            "107",     ["visa", "verve"]),
    ("Parallex Bank",           "104",     ["visa", "verve"]),
    ("Premium Trust Bank",      "105",     ["visa", "verve"]),
    ("Providus Bank",           "101",     ["mastercard", "verve"]),
    ("Rand Merchant Bank",      "502",     ["visa"]),
    ("Signature Bank",          "106",     ["visa", "verve"]),
    ("Summit Bank",             "00305",   ["visa", "verve"]),
    ("Suntrust Bank",           "100",     ["visa", "verve"]),
    ("TAJ Bank",                "302",     ["mastercard", "verve"]),
    ("Titan Trust Bank",        "102",     ["visa", "mastercard", "verve"]),
    # ── Payment Service Banks (PSB) — Verve only ─────────────────────────────
    ("OPay (PSB)",              "999992",  ["verve"]),
    ("PalmPay (PSB)",           "999991",  ["verve"]),
    ("HopePSB",                 "120002",  ["verve"]),
    ("MTN MoMo PSB",            "120003",  ["verve"]),
    ("Airtel SmartCash PSB",    "120004",  ["verve"]),
    ("9mobile 9PSB",            "120001",  ["verve"]),
    # ── Digital / Fintech banks & MFBs ───────────────────────────────────────
    ("Kuda Bank",               "50211",   ["mastercard", "verve"]),
    ("Carbon (OneFi)",          "565",     ["mastercard", "verve"]),
    ("Dot MFB",                 "50162",   ["mastercard", "verve"]),
    ("Eyowo",                   "50126",   ["verve"]),
    ("FairMoney MFB",           "51318",   ["verve"]),
    ("Moniepoint MFB",          "50515",   ["verve"]),
    ("PocketApp",               "00716",   ["mastercard", "verve"]),
    ("Rubies MFB",              "125",     ["visa", "verve"]),
    ("Safe Haven MFB",          "51113",   ["visa", "verve"]),
    ("Sparkle MFB",             "51310",   ["mastercard", "verve"]),
    ("Tangerine Money",         "51269",   ["mastercard", "verve"]),
    ("VFD MFB",                 "566",     ["visa", "verve"]),
    ("Bankly MFB",              "51341",   ["verve"]),
    ("LAPO MFB",                "090177",  ["verve"]),
    ("NPF MFB",                 "50629",   ["verve"]),
    ("Accion MFB",              "602",     ["verve"]),
    ("Baobab MFB",              "MFB50992",["verve"]),
]

# ---------------------------------------------------------------------------
# Paystack BIN-confirmed card network data
# Keys are lowercase canonical bank name patterns.
# Values are sets of networks CONFIRMED via /decision/bin/{bin} probing.
# "Not listed" means unconfirmed, NOT absent — heuristics fill the gap.
# ---------------------------------------------------------------------------
PAYSTACK_BIN_NETWORKS = {
    # Tier-1 commercial — confirmed from BIN scans
    "access bank":                     {"visa", "mastercard", "verve"},
    "access bank (diamond)":           {"visa", "mastercard", "verve"},
    "access bank diamond":             {"visa", "mastercard", "verve"},
    "ecobank nigeria":                 {"visa", "verve"},
    "fidelity bank":                   {"visa", "verve"},
    "first bank of nigeria":           {"mastercard", "verve"},
    "first city monument bank":        {"verve"},
    "fcmb":                            {"verve"},
    "guaranty trust bank":             {"mastercard", "verve"},
    "gtbank":                          {"mastercard", "verve"},
    "heritage bank":                   {"mastercard", "verve"},
    "jaiz bank":                       {"verve"},
    "keystone bank":                   {"visa", "verve"},
    "polaris bank":                    {"visa", "mastercard", "verve"},
    "providus bank":                   {"mastercard", "verve"},
    "stanbic ibtc bank":               {"verve"},
    "sterling bank":                   {"verve"},
    "taj bank":                        {"verve"},
    "titan bank":                      {"mastercard"},
    "titan trust bank":                {"mastercard"},
    "united bank for africa":          {"visa", "mastercard", "verve"},
    "uba":                             {"visa", "mastercard", "verve"},
    "union bank of nigeria":           {"mastercard", "verve"},
    "union bank":                      {"mastercard", "verve"},
    "unity bank":                      {"mastercard", "verve"},
    "wema bank":                       {"verve"},
    "zenith bank":                     {"visa", "mastercard", "verve"},
    # PSBs — Verve only confirmed (CBN regulation)
    "opay (psb)":                      {"verve"},
    "palmpay (psb)":                   {"verve"},
    "opay digital services":           {"verve"},
    "palmpay":                         {"verve"},
    "opay":                            {"verve"},
    "hopepsb":                         {"verve"},
    "hope psb":                        {"verve"},
    "9mobile 9psb":                    {"verve"},
    "mtn momo psb":                    {"verve"},
    "airtel smartcash psb":            {"verve"},
    # Digital / fintech banks
    "kuda bank":                       {"visa"},
    "moniepoint":                      {"mastercard"},
    "moniepoint mfb":                  {"mastercard"},
    "tangerine":                       {"mastercard"},
    "tangerine money":                 {"mastercard"},
    # MFBs / others — Verve only confirmed
    "accion microfinance bank":        {"verve"},
    "accion mfb":                      {"verve"},
    "fairmoney mfb":                   {"verve"},
    "lapo microfinance bank":          {"verve"},
    "lapo mfb":                        {"verve"},
    "suntrust bank":                   {"verve"},
    "hasal microfinance bank":         {"verve"},
    "infinity trust mortgage bank":    {"verve"},
    "ekondo microfinance bank":        {"verve"},
    "nigerian police force mfb":       {"verve"},
    "npf mfb":                         {"verve"},
    "aso savings and loans":           {"verve"},
    "fbn micro finance bank":          {"verve"},
    "fbn mfb":                         {"verve"},
}

_BIN_CACHE_PATH = _CONFIG_DIR / "bin_cache.json"


def _norm_bank(name: str) -> str:
    """Lowercase, collapse spaces, strip non-alphanumeric for fuzzy matching."""
    import re as _re
    return _re.sub(r"[^a-z0-9 ]", " ", (name or "").lower()).split()


def _bin_match(name: str) -> set:
    """
    Return the set of Paystack-confirmed networks for a bank name,
    checking PAYSTACK_BIN_NETWORKS first, then the loaded cache.
    Returns empty set if no match.
    """
    toks = _norm_bank(name)
    best: set = set()

    # Also check disk cache (updated by scan_bin_database)
    cache_data: dict = {}
    try:
        if _BIN_CACHE_PATH.exists():
            cache_data = json.loads(_BIN_CACHE_PATH.read_text())
    except Exception:
        pass

    all_sources = dict(PAYSTACK_BIN_NETWORKS)
    all_sources.update({k: set(v) for k, v in cache_data.items()})

    for key, nets in all_sources.items():
        ktoks = _norm_bank(key)
        # exact token-set match or one contains the other (at least 2 tokens)
        if toks == ktoks:
            return set(nets)
        if len(toks) >= 2 and len(ktoks) >= 2:
            if all(t in ktoks for t in toks) or all(t in toks for t in ktoks):
                if len(set(nets)) > len(best):
                    best = set(nets)

    return best


def scan_bin_database(key: str, verbose: bool = True) -> dict:
    """
    Probe a curated set of Nigerian BINs via Paystack /decision/bin/{bin}.
    Groups results by bank → confirmed networks and saves to cache.
    Returns {bank_name_lower: [network, ...]} dict.
    """
    CURATED_BINS = [
        # Verve — 5061xx range
        "506101","506102","506103","506105","506106","506107","506108","506109",
        "506110","506115","506116","506117","506118","506119","506120","506123",
        "506126","506137","506138","506143","506144","506146","506166","506177",
        "506180","506195",
        # Verve — 650xxx range
        "650003","650004","650005","650006","650007",
        # Mastercard confirmed Nigerian BINs
        "539326","539983","539923","539941","539945","539586","539185",
        "516195","516227","516256","516491","536024","536088","536399",
        # Visa confirmed Nigerian BINs
        "403660","404930","405030","408410","410540","422500","428500",
        "444950","450090",
    ]

    if verbose:
        print(c("\n  Scanning Paystack BIN database...", C.CYAN), flush=True)

    result: dict[str, set] = {}

    for bin6 in CURATED_BINS:
        try:
            data = _curl_get(
                f"https://api.paystack.co/decision/bin/{bin6}",
                {"Authorization": f"Bearer {key}"},
            ).get("data") or {}
        except ProviderError:
            continue

        brand   = (data.get("brand") or "").lower().strip()
        bank    = (data.get("bank") or "").strip()
        country = (data.get("country_code") or "").strip()

        if not bank or not brand or country not in ("NG", ""):
            continue

        # Normalise brand → network name
        if "verve" in brand:
            net = "verve"
        elif "mastercard" in brand:
            net = "mastercard"
        elif "visa" in brand:
            net = "visa"
        else:
            continue

        key_n = " ".join(_norm_bank(bank))
        result.setdefault(key_n, set()).add(net)

        if verbose:
            print(f"    {bin6}  {brand:<14}  {bank}", flush=True)

    # Persist to cache
    try:
        _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        cache_out = {k: sorted(v) for k, v in result.items()}
        _BIN_CACHE_PATH.write_text(json.dumps(cache_out, indent=2))
        if verbose:
            print(c(f"\n  Saved {len(result)} bank entries to cache.", C.GREEN))
    except Exception as e:
        if verbose:
            print(c(f"\n  Cache save failed: {e}", C.YELLOW))

    return {k: set(v) for k, v in result.items()}


# Live probe targets for each card network / processing layer
# Each entry: (label, url, expected_codes)
CARD_NET_PROBES = {
    "visa": [
        ("Visa Global",            "https://www.visa.com",                     {200,301,302,403}),
        ("Visa Nigeria",           "https://www.visa.com.ng",                  {200,301,302,403}),
        ("Visa Developer Hub",     "https://developer.visa.com",               {200,301,302,403}),
        ("CyberSource (Visa GW)",  "https://www.cybersource.com",              {200,301,302,403}),
    ],
    "mastercard": [
        ("Mastercard Global",      "https://www.mastercard.com",               {200,301,302,403}),
        ("Mastercard Nigeria",     "https://www.mastercard.com.ng",            {200,301,302,403}),
        ("MC Developer Portal",    "https://developer.mastercard.com",         {200,301,302,403}),
        ("MC Gateway (MPGS)",      "https://ap-gateway.mastercard.com",        {200,301,302,403,404}),
    ],
    "verve": [
        ("Interswitch Group",      "https://www.interswitch.com",              {200,301,302,403}),
        ("WebPay Gateway",         "https://webpay.interswitchng.com",         {200,301,302,403}),
        ("Quickteller",            "https://www.quickteller.com",              {200,301,302,403}),
        ("Interswitch Passport",   "https://passport.interswitchng.com",       {200,301,302,400,401,403,404}),
    ],
    "nibss": [
        ("NIBSS Website",          "https://www.nibss-plc.com.ng",             {200,301,302,403}),
        ("NIBSS e-BillsPay",       "https://www.nibss-plc.com.ng/nibss-ebillspay", {200,301,302,403,404}),
    ],
}

def _probe_endpoint(url, expected_codes, timeout=10):
    """Probe a URL with curl. Returns (status_code, latency_ms) or (None, None)."""
    try:
        import time as _time
        t0 = _time.monotonic()
        result = subprocess.run(
            ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}",
             "--max-time", str(timeout), "--connect-timeout", "8",
             "-L", "--max-redirs", "3", url],
            capture_output=True, timeout=timeout + 5,
        )
        ms = int((_time.monotonic() - t0) * 1000)
        code = result.stdout.decode().strip()
        code = int(code) if code.isdigit() else None
        return code, ms
    except Exception:
        return None, None


def _probe_network_status_fast() -> dict:
    """
    Probe Visa/MC/Verve gateways concurrently.
    Returns {network: ("online"|"degraded"|"offline", avg_ms)}.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed as _as_completed

    bucket: dict = {"visa": [], "mastercard": [], "verve": []}

    def _check(net, url, expected):
        code, ms = _probe_endpoint(url, expected, timeout=8)
        if code is not None and code in expected:
            return net, "online", ms
        elif code is not None:
            return net, "degraded", ms
        return net, "offline", None

    futures = []
    with ThreadPoolExecutor(max_workers=12) as ex:
        for net, probes in CARD_NET_PROBES.items():
            if net == "nibss":
                continue
            for _, url, expected in probes:
                futures.append(ex.submit(_check, net, url, expected))
        for f in _as_completed(futures):
            try:
                net, status, ms = f.result()
                bucket[net].append((status, ms))
            except Exception:
                pass

    out = {}
    for net, items in bucket.items():
        if not items:
            out[net] = ("offline", None)
            continue
        statuses = [s for s, _ in items]
        ms_vals  = [m for _, m in items if m is not None]
        avg_ms   = int(sum(ms_vals) / len(ms_vals)) if ms_vals else None
        if all(s == "online" for s in statuses):
            out[net] = ("online", avg_ms)
        elif any(s == "online" for s in statuses):
            out[net] = ("degraded", avg_ms)
        else:
            out[net] = ("offline", avg_ms)
    return out


def monitor_card_network_status():
    """Live probe of Visa / Mastercard / Verve / NIBSS processing endpoints."""
    print()
    print("  " + c("┌─ Card Network Status Monitor ", C.MAGENTA + C.BOLD) + c("─" * 31, C.MAGENTA))
    print("  " + c("│ ", C.MAGENTA) + c("Probing payment processing gateways for POS/debit...", C.GREY))
    print("  " + c("└" + "─" * 60, C.MAGENTA))
    print()

    net_labels = {
        "visa":       ("VISA",          C.BLUE  + C.BOLD),
        "mastercard": ("MASTERCARD",    C.RED   + C.BOLD),
        "verve":      ("VERVE",         C.GREEN + C.BOLD),
        "nibss":      ("NIBSS (NIP)",   C.YELLOW + C.BOLD),
    }

    total_up = total_down = 0

    for net_key, probes in CARD_NET_PROBES.items():
        label, color = net_labels[net_key]
        print("  " + c(f"● {label}", color))
        print(c("  " + "─" * 60, C.GREY))

        net_up = net_down = 0
        for name, url, expected in probes:
            sys.stdout.write(f"    probing {name:<34}")
            sys.stdout.flush()
            code, ms = _probe_endpoint(url, expected)

            if code is not None and code in expected:
                dot   = c("● ONLINE ", C.GREEN + C.BOLD)
                lag   = c(f"{ms:>5}ms", C.CYAN)
                net_up += 1
            elif code is not None:
                dot   = c("● DEGRADED", C.YELLOW + C.BOLD)
                lag   = c(f"{ms:>5}ms  [HTTP {code}]", C.YELLOW)
                net_down += 1
            else:
                dot   = c("● OFFLINE ", C.RED + C.BOLD)
                lag   = c("  timeout", C.RED)
                net_down += 1

            # clear the "probing..." line and print result
            sys.stdout.write(f"\r    {dot}  {lag}  {name}\n")

        total_up   += net_up
        total_down += net_down
        summary_col = C.GREEN + C.BOLD if net_down == 0 else (C.YELLOW + C.BOLD if net_up > 0 else C.RED + C.BOLD)
        status_str  = "ALL UP" if net_down == 0 else (f"{net_down} DOWN" if net_up == 0 else f"{net_down} DEGRADED")
        print(c(f"  {status_str}", summary_col))
        print()

    overall = C.GREEN + C.BOLD if total_down == 0 else (C.YELLOW + C.BOLD if total_up > 0 else C.RED + C.BOLD)
    total = total_up + total_down
    print(c("  " + "─" * 60, C.GREY))
    print("  " + c(f"Overall: {total_up}/{total} endpoints UP", overall))
    print()


_NETWORK_ICONS = {
    "visa":       "VISA",
    "mastercard": "MASTERCARD",
    "verve":      "VERVE",
}


def _detect_verve(bin8):
    for pfx in _VERVE_PREFIXES:
        if bin8.startswith(pfx):
            return True
    return False


def _local_scheme(bin6):
    """
    Detect card scheme locally from BIN prefix — instant, no API needed.
    Returns (scheme, brand) or ("unknown", "Unknown").
    """
    n = bin6
    # Verve (must check before Mastercard — some Verve BINs start with 5)
    if _detect_verve(n):
        return "verve", "Verve (Interswitch)"
    # Visa: starts with 4
    if n.startswith("4"):
        return "visa", "Visa"
    # Mastercard: 51–55 or IIN range 2221–2720
    if n[:2] in ("51", "52", "53", "54", "55"):
        return "mastercard", "Mastercard"
    pfx4 = int(n[:4]) if n[:4].isdigit() else 0
    if 2221 <= pfx4 <= 2720:
        return "mastercard", "Mastercard"
    # American Express: 34 / 37
    if n[:2] in ("34", "37"):
        return "amex", "American Express"
    # Discover / Verve 6500 overlap already handled above
    if n[:4] in ("6011",) or n[:2] == "65":
        return "discover", "Discover"
    return "unknown", "Unknown"


def _binlist_enrich(bin6):
    """
    Try to get issuer name, card type, and country from binlist.net.
    Returns a partial dict or {} on any error / rate-limit.
    """
    try:
        result = subprocess.run(
            ["curl", "-s", "--max-time", "10",
             "-H", "Accept-Version: 3",
             url := f"https://lookup.binlist.net/{bin6}"],
            capture_output=True, timeout=15,
        )
        body = result.stdout.decode("utf-8", "replace").strip()
        if not body:
            return {}
        data = json.loads(body)
        if not data.get("scheme"):
            return {}
        return {
            "type":    data.get("type", ""),
            "brand":   data.get("brand", ""),
            "prepaid": data.get("prepaid", False),
            "bank":    data.get("bank") or {},
            "country": data.get("country") or {},
        }
    except Exception:
        return {}


def lookup_bin(raw):
    """
    Look up a card BIN (first 6–8 digits of card number).
    Returns (info_dict, None) or (None, error_string).
    """
    digits = re.sub(r"\D", "", raw)
    if len(digits) < 6:
        return None, "Need at least 6 digits"

    bin6 = digits[:6]
    masked = bin6 + "x" * max(0, len(digits) - 6)

    # Always detect scheme locally — instant and reliable
    scheme, brand = _local_scheme(bin6)
    if scheme == "unknown":
        return None, f"Unrecognised BIN prefix: {bin6[:4]}xx"

    info = {
        "scheme":  scheme,
        "brand":   brand,
        "type":    "debit" if scheme == "verve" else "",
        "prepaid": False,
        "bank":    {"name": "Nigerian Issuer"} if scheme == "verve" else {},
        "country": {"name": "Nigeria", "alpha2": "NG", "emoji": "🇳🇬"} if scheme == "verve" else {},
        "bin":     bin6,
        "masked":  masked,
    }

    # Enrich with live data from binlist (best-effort — silently skipped on rate-limit)
    if scheme != "verve":
        extra = _binlist_enrich(bin6)
        if extra:
            if extra.get("brand"):
                info["brand"] = extra["brand"]
            if extra.get("type"):
                info["type"] = extra["type"]
            info["prepaid"] = extra.get("prepaid", False)
            if extra.get("bank"):
                info["bank"] = extra["bank"]
            if extra.get("country"):
                info["country"] = extra["country"]

    return info, None


def _print_card_result(info):
    scheme  = info.get("scheme", "unknown")
    brand   = info.get("brand", scheme.title())
    kind    = info.get("type", "unknown").title()
    prepaid = "Prepaid" if info.get("prepaid") else ""
    bank    = (info.get("bank") or {}).get("name", "Unknown issuer")
    country = (info.get("country") or {}).get("name", "Unknown")
    emoji   = (info.get("country") or {}).get("emoji", "")
    color   = _NETWORK_COLORS.get(scheme, C.GREY)
    icon    = _NETWORK_ICONS.get(scheme, brand.upper())
    label   = " / ".join(filter(None, [kind, prepaid])) or "Unknown"

    print()
    print("  " + c("╔" + "═" * 58 + "╗", color))
    title = f"  ✓  {icon}"
    print("  " + c("║", color) + c(title, color) +
          " " * (58 - len(title)) + c("║", color))
    print("  " + c("╠" + "═" * 58 + "╣", color))

    def row(label, val, vc):
        plain = f"  {label} : {val}"
        pad = " " * max(0, 58 - len(plain))
        return "  " + c("║", color) + f"  {label} : " + c(val, vc) + pad + c("║", color)

    print(row("Network  ", brand,                  color))
    print(row("BIN      ", info.get("bin", "?"),   C.WHITE + C.BOLD))
    print(row("Card Type", label,                  C.CYAN))
    print(row("Issuer   ", bank,                   C.YELLOW + C.BOLD))
    print(row("Country  ", f"{emoji} {country}".strip(), C.WHITE))
    print("  " + c("╚" + "═" * 58 + "╝", color))
    print()


def _guess_networks(name, code):
    """
    Infer Visa/Mastercard/Verve from CARD_NETWORK_DB then heuristics.
    Returns a list of network names (estimated, not BIN-confirmed).
    """
    known = {e[1]: e[2] for e in CARD_NETWORK_DB}
    if code in known:
        return known[code]

    n  = (name or "").upper()
    c_ = str(code or "")

    if c_.startswith("120") or c_ in ("999992", "999991"):
        return ["verve"]

    if any(k in n for k in ("MERCHANT", "FSDH", "RAND ", "CORONATION", "GREENWICH", "NOVA BANK",
                             "FBN QUEST", "FBNQUEST", "STANBIC IBTC NOMINEES")):
        return ["visa"]

    if "MORTGAGE" in n or "SAVINGS" in n:
        return ["verve"]

    digital = ("KUDA", "CARBON", "DOT MFB", "SPARKLE", "TANGERINE", "POCKET",
                "VFD", "RUBIES", "SAFE HAVEN", "EYOWO", "FAIRMONEY", "BANKLY",
                "MONIEPOINT", "LAPO", "NPF MFB", "ACCION", "BAOBAB")
    if any(k in n for k in digital):
        if any(k in n for k in ("KUDA", "CARBON", "DOT MFB", "SPARKLE",
                                "TANGERINE", "POCKET", "VFD")):
            return ["mastercard", "verve"]
        return ["verve"]

    if "MICROFINANCE" in n or "MFB" in n or c_.startswith("090") or (
            len(c_) >= 5 and c_[:2] in ("50", "51", "65")):
        return ["verve"]

    if (c_.isdigit() and len(c_) <= 3) or c_.startswith("00"):
        return ["visa", "mastercard", "verve"]

    return ["verve"]


def _resolve_networks(name: str, code: str):
    """
    Return (confirmed, estimated) network sets for a bank.
    confirmed  — verified via Paystack BIN endpoint (solid ●)
    estimated  — from heuristics but not BIN-confirmed (hollow ○)
    """
    confirmed = _bin_match(name)
    estimated = set(_guess_networks(name, code)) - confirmed
    return confirmed, estimated


def monitor_card_networks(provider=None, filter_net=None):
    """
    Display all NG banks with their Visa / MC / Verve issuance AND live
    network status in one combined view.

    Column colour coding:
      ● bright green  = bank issues this card  +  network ONLINE
      ● yellow        = bank issues this card  +  network DEGRADED
      ● red           = bank issues this card  +  network OFFLINE
      ○ (same rules) = bank likely issues it  (estimated, not BIN-confirmed)
      ─ grey          = bank does not issue this card
    """
    print()
    print("  " + c("┌─ Card Network Monitor ", C.MAGENTA + C.BOLD) + c("─" * 38, C.MAGENTA))
    print("  " + c("│ ", C.MAGENTA) +
          c("All NG banks — card issuance + live network status", C.GREY))
    print("  " + c("└" + "─" * 60, C.MAGENTA))
    print()

    # ── 1. Fetch bank list ────────────────────────────────────────────────────
    live_banks = []
    if provider:
        spinner("Fetching bank list...")
        try:
            live_banks = provider.list_banks()
            print(c("done", C.GREEN) + c(f"  ({len(live_banks)} banks)", C.GREY))
        except ProviderError as e:
            print(c(f"failed ({e}) — using built-in list", C.YELLOW))

    if live_banks:
        live_codes = {b["code"] for b in live_banks}
        rows = [(b["name"], b["code"]) for b in live_banks]
        for name, code, _ in CARD_NETWORK_DB:
            if code not in live_codes:
                rows.append((name, code))
    else:
        rows = [(name, code) for name, code, _ in CARD_NETWORK_DB]

    if filter_net:
        rows = [(n, co) for n, co in rows
                if filter_net in (_resolve_networks(n, co)[0] | _resolve_networks(n, co)[1])]

    # ── 2. Probe live network gateways (concurrent) ───────────────────────────
    spinner("Probing live card network gateways...")
    net_status = _probe_network_status_fast()   # {net: ("online"|"degraded"|"offline", avg_ms)}
    print(c("done", C.GREEN))

    # ── 3. Build per-network status colours / labels ──────────────────────────
    _STATUS_COLOR = {
        "online":   C.GREEN  + C.BOLD,
        "degraded": C.YELLOW + C.BOLD,
        "offline":  C.RED    + C.BOLD,
    }
    _NET_BASE_COLOR = {
        "visa":       C.BLUE,
        "mastercard": C.RED,
        "verve":      C.GREEN,
    }

    def _status_label(net):
        status, avg_ms = net_status.get(net, ("offline", None))
        col  = _STATUS_COLOR[status]
        icon = {"online": "● ONLINE", "degraded": "● DEGRADED", "offline": "● OFFLINE"}[status]
        lag  = f" {avg_ms}ms" if avg_ms else ""
        return c(icon + lag, col)

    NO = c(" ─ ", C.GREY)

    def _mark(net, is_conf, is_est):
        """Return the display marker for one cell, coloured by live status."""
        if not is_conf and not is_est:
            return NO
        status, _ = net_status.get(net, ("offline", None))
        col = _STATUS_COLOR[status]
        dot = "●" if is_conf else "○"
        return c(f" {dot} ", col)

    # ── 4. Print network status banner ───────────────────────────────────────
    print(
        "  " + c("Network status:  ", C.WHITE + C.BOLD) +
        c("VISA ", C.BLUE + C.BOLD)   + _status_label("visa")       + "   " +
        c("MC ", C.RED + C.BOLD)      + _status_label("mastercard") + "   " +
        c("VERVE ", C.GREEN + C.BOLD) + _status_label("verve")
    )
    print()

    # ── 5. Print per-bank table ───────────────────────────────────────────────
    header = (
        "  " + c(f"{'#':>3}  {'BANK':<35}{'CODE':<10}", C.BOLD + C.WHITE) +
        c(" VISA", C.BLUE  + C.BOLD) +
        c("   MC", C.RED   + C.BOLD) +
        c(" VERVE", C.GREEN + C.BOLD)
    )
    print(header)
    print(c("  " + "─" * 70, C.GREY))

    visa_count = mc_count = verve_count = 0
    confirmed_rows = 0

    for i, (bank, code) in enumerate(rows, 1):
        conf, est = _resolve_networks(bank, code)
        all_nets  = conf | est

        has_v  = "visa"       in all_nets
        has_mc = "mastercard" in all_nets
        has_vv = "verve"      in all_nets

        if has_v:  visa_count  += 1
        if has_mc: mc_count    += 1
        if has_vv: verve_count += 1
        if conf:   confirmed_rows += 1

        vm  = _mark("visa",       "visa"       in conf, "visa"       in est)
        mcm = _mark("mastercard", "mastercard" in conf, "mastercard" in est)
        vvm = _mark("verve",      "verve"      in conf, "verve"      in est)

        idx   = c(f"{i:>3}", C.GREY)
        bname = c(f"{bank:<35.35}", C.WHITE)
        bcode = c(f"{code:<10}", C.CYAN)
        print(f"  {idx}  {bname}{bcode}{vm}{mcm}{vvm}")

    # ── 6. Footer ─────────────────────────────────────────────────────────────
    print(c("  " + "─" * 70, C.GREY))
    print(
        "  " + c(f"Total: {len(rows)} banks", C.WHITE) +
        c(f"   VISA: {visa_count}", C.BLUE + C.BOLD) +
        c(f"   MC: {mc_count}", C.RED + C.BOLD) +
        c(f"   VERVE: {verve_count}", C.GREEN + C.BOLD)
    )
    print(
        "  " + c(f"BIN-confirmed: {confirmed_rows} banks", C.CYAN) +
        c("   ● confirmed   ○ estimated   colour = live network status", C.GREY)
    )
    print()


def card_lookup_interactive():
    print()
    raw = input("  " + c("Enter card number or BIN (first 6–16 digits): ", C.CYAN)).strip()
    if not raw:
        print("  " + c("No input.\n", C.RED))
        return
    spinner("Looking up BIN...")
    info, err = lookup_bin(raw)
    if err:
        print(c("FAILED", C.RED))
        print("  " + c(f"✗ {err}", C.RED))
        print()
        return
    print(c("OK", C.GREEN + C.BOLD))
    _print_card_result(info)


# --------------------------------------------------------------------------- #
#  Interactive menu
# --------------------------------------------------------------------------- #
def menu():
    print("  " + c("Select an option:", C.BOLD + C.WHITE))
    print("    " + c("[1]", C.CYAN + C.BOLD) + " Validate a bank account   " +
          c("(NUBAN name enquiry)", C.GREY))
    print("    " + c("[2]", C.CYAN + C.BOLD) + " Bank network monitor       " +
          c("(all active NG banks)", C.GREY))
    print("    " + c("[3]", C.CYAN + C.BOLD) + " Card network status        " +
          c("(live Visa/MC/Verve POS gateway probe)", C.GREY))
    print("    " + c("[4]", C.CYAN + C.BOLD) + " Card issuance matrix       " +
          c("(which banks issue Visa / MC / Verve — Paystack BIN data)", C.GREY))
    print("    " + c("[5]", C.CYAN + C.BOLD) + " Card BIN lookup            " +
          c("(identify a card from its number)", C.GREY))
    print("    " + c("[6]", C.CYAN + C.BOLD) + " Active bank networks only")
    print("    " + c("[7]", C.CYAN + C.BOLD) + " About")
    print("    " + c("[8]", C.YELLOW + C.BOLD) + " Set API key               " +
          c("(Paystack / NubAPI)", C.GREY))
    print("    " + c("[9]", C.YELLOW + C.BOLD) + " Refresh BIN database       " +
          c("(re-probe Paystack BINs, update card network cache)", C.GREY))
    print("    " + c("[0]", C.RED + C.BOLD) + " Exit")
    print()


def interactive():
    banner()
    provider = None
    try:
        provider = build_provider(verbose=True)
        prov_line = c(f"Backend: {provider.name}", C.GREEN)
    except ProviderError as e:
        prov_line = c("Backend: UNAVAILABLE", C.RED) + \
                    c(f"  ({str(e).splitlines()[0]})", C.GREY)
    cfg = _load_config()
    key_src = ""
    if os.environ.get("PAYSTACK_SECRET_KEY") or os.environ.get("PAYSTACK_KEY"):
        key_src = c("  (env var)", C.GREY)
    elif os.environ.get("NUBAPI_TOKEN"):
        key_src = c("  (env var)", C.GREY)
    elif cfg.get("provider"):
        key_src = c("  (saved config)", C.GREY)
    else:
        key_src = c("  (auto-acquired)", C.GREY)
    print("  " + prov_line + key_src)
    print()

    while True:
        menu()
        try:
            choice = input("  " + c("krainium➤ ", C.MAGENTA + C.BOLD)).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if choice == "0":
            break
        if choice not in {"1", "2", "3", "4", "5", "6", "7", "8", "9"}:
            print("  " + c("Invalid option.\n", C.RED))
            continue

        if choice == "7":
            _about()
            continue

        if choice == "8":
            result = manage_api_key()
            if result == "rebuild":
                # Rebuild the provider with the newly saved key
                try:
                    provider = build_provider(verbose=False)
                    print("  " + c(f"✓ Now using: {provider.name}", C.GREEN + C.BOLD))
                except ProviderError as e:
                    print("  " + c(f"✗ {e}", C.RED))
                    provider = None
                print()
            continue

        if choice == "3":
            monitor_card_network_status()
            continue

        if choice == "4":
            monitor_card_networks(provider=provider)
            continue

        if choice == "5":
            card_lookup_interactive()
            continue

        if choice == "9":
            # Refresh BIN database via Paystack — requires Paystack key
            ps_key = None
            if isinstance(provider, PaystackProvider):
                ps_key = provider.key
            else:
                cfg = _load_config()
                if cfg.get("provider") == "paystack":
                    ps_key = cfg.get("key")
                env_key = os.environ.get("PAYSTACK_SECRET_KEY") or os.environ.get("PAYSTACK_KEY")
                if env_key:
                    ps_key = env_key
            if not ps_key:
                print("  " + c("✗ Paystack key required for BIN scan. Set it via [8].", C.RED))
                print()
            else:
                scan_bin_database(ps_key, verbose=True)
            continue

        if provider is None:
            print()
            print("  " + c("✗ Backend unavailable.", C.RED + C.BOLD))
            print()
            continue

        if choice == "1":
            acct = input("  " + c("Enter account number: ", C.CYAN)).strip()
            if not acct:
                print("  " + c("No account entered.\n", C.RED))
                continue
            bank = input("  " + c("Enter bank code (blank = auto-scan all banks): ", C.CYAN)).strip()
            validate_account(provider, acct, bank_code=bank or None)
        elif choice == "2":
            monitor_banks(provider, only_active=False)
        elif choice == "6":
            monitor_banks(provider, only_active=True)


def _about():
    print()
    print("  " + c("Bank Account Validator & Monitor (NG)", C.GREEN + C.BOLD))
    print("  " + c("made by Krainium", C.MAGENTA))
    print()
    print("  " + c("Backend: NubAPI (nubapi.com)", C.GREY))
    print("  " + c("• Token auto-acquired from NubAPI register page (no key needed)", C.GREY))
    print("  " + c("• Falls back to Mailinator auto-registration for personal token", C.GREY))
    print("  " + c("• Bank list: public /bank-json (707+ NG banks, no auth)", C.GREY))
    print("  " + c("• Resolution: /api/verify (NIBSS name enquiry)", C.GREY))
    print()


# --------------------------------------------------------------------------- #
#  Entry
# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser(description="Bank Account Validator & Monitor (NG)")
    ap.add_argument("--account", "-a", help="account number to validate")
    ap.add_argument("--bank",    "-b", help="bank code (optional; blank = auto-scan)")
    ap.add_argument("--monitor", "-m", action="store_true", help="list banks with status")
    ap.add_argument("--active-only",   action="store_true", help="monitor: active banks only")
    ap.add_argument("--card",         "-c", help="card BIN / number to look up (first 6–16 digits)")
    ap.add_argument("--card-monitor", "-C", action="store_true",
                    help="live probe: Visa/MC/Verve gateway status for POS/debit")
    ap.add_argument("--card-matrix",        action="store_true",
                    help="show card issuance matrix (which banks issue each scheme)")
    ap.add_argument("--filter-net",         choices=["visa","mastercard","verve"],
                    help="filter card monitor to one network")
    ap.add_argument("--reset-token",   action="store_true",
                    help="delete cached token and re-acquire a fresh one")
    ap.add_argument("--scan-bins",     action="store_true",
                    help="probe Paystack BIN endpoints to refresh card network cache")
    args = ap.parse_args()

    if args.reset_token and _TOKEN_CACHE.exists():
        _TOKEN_CACHE.unlink()
        print(c("Cached token cleared.", C.YELLOW))

    if args.scan_bins:
        banner()
        try:
            provider = build_provider(verbose=True)
        except ProviderError as e:
            print("  " + c(f"✗ {e}", C.RED))
            sys.exit(2)
        if not isinstance(provider, PaystackProvider):
            print("  " + c("✗ Paystack key required for --scan-bins.", C.RED))
            sys.exit(2)
        scan_bin_database(provider.key, verbose=True)
        return

    if args.card_monitor:
        banner()
        monitor_card_network_status()
        return

    if args.card_matrix:
        banner()
        try:
            provider = build_provider(verbose=True)
        except ProviderError:
            provider = None
        monitor_card_networks(provider=provider, filter_net=getattr(args, "filter_net", None))
        return

    if args.card:
        banner()
        spinner(f"Looking up BIN for {args.card[:6]}xxxxxx...")
        info, err = lookup_bin(args.card)
        if err:
            print(c("FAILED", C.RED))
            print("  " + c(f"✗ {err}", C.RED))
            sys.exit(2)
        print(c("OK", C.GREEN + C.BOLD))
        _print_card_result(info)
        return

    if args.account or args.monitor:
        banner()
        try:
            provider = build_provider(verbose=True)
        except ProviderError as e:
            print("  " + c("✗ " + str(e), C.RED + C.BOLD))
            sys.exit(2)
        print("  " + c(f"Backend: {provider.name}", C.GREEN) + "\n")
        if args.monitor:
            monitor_banks(provider, only_active=args.active_only)
        if args.account:
            ok = validate_account(provider, args.account, bank_code=args.bank or None)
            sys.exit(0 if ok else 1)
        return

    interactive()


if __name__ == "__main__":
    main()
