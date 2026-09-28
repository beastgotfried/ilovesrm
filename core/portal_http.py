"""Pure-HTTP client for the SRM eCurricula portal.

Zero browser / WebBridge dependency — talks directly to the portal REST API
at https://dld.srmist.edu.in/ktretecurricula/server/curricula/* using only
the Python standard library.

Auth model
----------
The portal's login endpoint enforces hCaptcha server-side, so unattended
password login needs a captcha-solver key (2captcha). The zero-dependency
path is token-based:

  1. Log in once in ANY browser (phone/laptop, no extension needed).
  2. In devtools console run:  copy(localStorage.jwtToken)
  3. Paste the token into the bot — it is cached in bot_config.json and
     refreshed automatically via /curricula/gettoken on every run.

All endpoint shapes below were reverse-engineered from the portal's own
frontend bundle (static/js/main.*.chunk.js, build "Version 10.0").
"""
import base64
import json
import os
import time
import urllib.request
import urllib.error

SERVER = "https://dld.srmist.edu.in/ktretecurricula/server"
KEY = "john"                      # literal app key baked into the frontend
HCAPTCHA_SITEKEY = "e3ce9522-434c-407e-beac-bdac1e74307a"
PAGE_URL = "https://dld.srmist.edu.in/ktretecurricula/"

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG = os.path.join(ROOT, "bot_config.json")


# --------------------------------------------------------------------------
# low level
# --------------------------------------------------------------------------
def _jwt_payload(token):
    """Decode the middle segment of a JWT (or 'Bearer :<jwt>') -> dict."""
    t = token.strip()
    if t.lower().startswith("bearer"):
        t = t.split(":", 1)[-1].strip()
    part = t.split(".")[1]
    part += "=" * (-len(part) % 4)
    return json.loads(base64.urlsafe_b64decode(part))


def _load_config():
    if os.path.exists(CONFIG):
        with open(CONFIG) as f:
            return json.load(f)
    return {}


def _save_config(cfg):
    with open(CONFIG, "w") as f:
        json.dump(cfg, f, indent=2)


class PortalError(RuntimeError):
    pass


class Portal:
    def __init__(self):
        self.token = None           # verbatim string the server issued
        self.info = None            # decoded JWT payload (common.user)
        self.courses = []           # from student/home/getcourses
        self.course_info = None     # COURSE_INFO of the open course

    # -- persistence -------------------------------------------------------
    def save(self):
        cfg = _load_config()
        cfg["portal"] = {"token": self.token, "info": self.info}
        _save_config(cfg)

    def load(self):
        p = _load_config().get("portal") or {}
        if p.get("token") and p.get("info"):
            self.token, self.info = p["token"], p["info"]
            return True
        return False

    # -- transport ----------------------------------------------------------
    def _post(self, path, body, timeout=60, auth=True):
        url = SERVER + path
        headers = {"Content-Type": "application/json;charset=utf-8"}
        if auth and self.token:
            # the frontend sets the header to the token string verbatim
            headers["Authorization"] = self.token
        req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                     headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:300]
            raise PortalError(f"HTTP {e.code} on {path}: {detail}")
        except urllib.error.URLError as e:
            raise PortalError(f"network error on {path}: {e.reason}")

    # -- auth ---------------------------------------------------------------
    def login_with_token(self, token):
        """Adopt a JWT copied from any logged-in browser session."""
        self.token = token.strip()
        self.info = _jwt_payload(self.token)
        # cheap validation: a read call must succeed
        self.list_courses()
        self.save()
        return self.identity()

    def login_with_password(self, user_id, password, captcha_api_key=None):
        """Password login. The portal enforces hCaptcha, so this needs a
        2captcha API key; without one it raises PortalError."""
        if not captcha_api_key:
            raise PortalError(
                "portal login enforces hCaptcha — provide a 2captcha API key "
                "or log in via login_with_token()")
        token = self._solve_hcaptcha(captcha_api_key)
        out = self._post("/curricula/login", {
            "USER_ID": user_id, "PASSWORD": password,
            "hcaptchaToken": token, "key": KEY}, auth=False)
        if out.get("Status") != 1:
            raise PortalError(f"login failed: {out.get('msg') or out}")
        return self.login_with_token(out["token"])

    def _solve_hcaptcha(self, api_key, poll=5, timeout=180):
        """2captcha hcaptcha solver (in.php / res.php)."""
        req = urllib.request.Request(
            "https://2captcha.com/in.php",
            data=json.dumps({
                "key": api_key, "method": "hcaptcha",
                "sitekey": HCAPTCHA_SITEKEY, "pageurl": PAGE_URL,
                "json": 1}).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            out = json.loads(r.read())
        if out.get("status") != 1:
            raise PortalError(f"2captcha submit failed: {out}")
        cid = out["request"]
        deadline = time.time() + timeout
        while time.time() < deadline:
            time.sleep(poll)
            with urllib.request.urlopen(
                    f"https://2captcha.com/res.php?key={api_key}&action=get"
                    f"&id={cid}&json=1", timeout=30) as r:
                out = json.loads(r.read())
            if out.get("status") == 1:
                return out["request"]
            if out.get("request") != "CAPCHA_NOT_READY":
                raise PortalError(f"2captcha failed: {out}")
        raise PortalError("2captcha timed out")

    def refresh(self):
        """Rotate the JWT via gettoken; updates cache. Best-effort: the
        endpoint is only used by the frontend for multi-login detection and
        intermittently 504s server-side, so failures are non-fatal."""
        try:
            out = self._post("/curricula/gettoken",
                             {"INFO": self.info, "KEY": KEY}, timeout=20)
        except Exception:
            return False
        new = out.get("result")
        if new and new != self.token:
            self.token = new
            self.info = _jwt_payload(new)
            self.save()
        return True

    # -- identity / courses -------------------------------------------------
    def identity(self):
        i = self.info or {}
        full = (i.get("FULL_NAME") or
                (i.get("FIRST_NAME", "") + " " + i.get("LAST_NAME", "")).strip())
        return {"reg": i.get("USER_ID"), "name": full,
                "department": i.get("DEPARTMENT"), "role": i.get("ROLE")}

    def full_name(self):
        """The portal sends FIRST_NAME+' '+LAST_NAME as FULL_NAME (which on
        this portal is often the full name doubled) — mirror it exactly."""
        i = self.info or {}
        if i.get("FIRST_NAME") is not None:
            return (i.get("FIRST_NAME", "") + " " + i.get("LAST_NAME", "")).strip()
        return i.get("FULL_NAME", "")

    def list_courses(self):
        out = self._post("/curricula/student/home/getcourses",
                         {"USER_ID": self.info["USER_ID"], "key": KEY})
        if out.get("Status") != 1:
            raise PortalError(f"getcourses failed: {out.get('msg') or out}")
        self.courses = out.get("courses") or []
        return self.courses

    def open_course(self, course_code):
        """Select a course; caches its COURSE_INFO (incl. BATCH_ID)."""
        if not self.courses:
            self.list_courses()
        for c in self.courses:
            if c.get("COURSE_CODE") == course_code or c.get("_id") == course_code:
                self.course_info = c
                return True
        raise PortalError(
            f"course {course_code} not in this account's course list "
            f"({[c.get('COURSE_CODE') for c in self.courses]})")

    # -- session reads ------------------------------------------------------
    def get_session_status(self, session):
        """session = unit*100+n (int, e.g. 201). Returns the result dict with
        PRACTICE {code: status}, SLOLINK {code: url}, MCQ {...}."""
        out = self._post("/curricula/student/session/getsessionstatus", {
            "USER_ID": self.info["USER_ID"],
            "FULL_NAME": self.full_name(),
            "DEPARTMENT": self.info.get("DEPARTMENT"),
            "COURSE_INFO": self.course_info,
            "SESSION": session,
            "key": KEY})
        if out.get("Status") != 1:
            raise PortalError(f"getsessionstatus failed: {out.get('msg') or out}")
        return out.get("result") or {}

    # -- writes -------------------------------------------------------------
    def submit_link(self, unit, session_n, slo, url):
        """Submit one worksheet link. Returns (ok, message)."""
        session = unit * 100 + session_n
        code = f"{session}{slo}"
        ci = self.course_info
        out = self._post("/curricula/student/session/submitlink", {
            "view": url, "download": url, "fileId": 0,
            "session": code, "SESSION": session, "SLO": slo,
            "course_code": ci.get("COURSE_CODE"),
            "course_name": ci.get("COURSE_NAME") or ci.get("COURSE_CODE"),
            "BATCH_ID": ci.get("BATCH_ID"),
            "USER_ID": self.info["USER_ID"],
            "FULL_NAME": self.full_name(),
            "DEPARTMENT": self.info.get("DEPARTMENT")})
        return out.get("Status") == 1, out.get("msg", "")


# --------------------------------------------------------------------------
# module-level facade — same call surface the pipeline already uses
# --------------------------------------------------------------------------
_session = Portal()

_PRACTICE_STATE = {2: "Verified", 1: "Submitted", 0: "Empty"}


def up():
    """True if we hold a token and the portal answers a read call."""
    if not _session.token and not _session.load():
        return False
    try:
        _session.list_courses()   # real validation; gettoken often 504s
        return True
    except Exception:
        return False


def login_with_token(token):
    return _session.login_with_token(token)


def login_with_password(user_id, password, captcha_api_key=None):
    return _session.login_with_password(user_id, password, captcha_api_key)


def detect_identity():
    who = _session.identity()
    return {"reg": who["reg"], "name": who["name"],
            "logged_in": bool(who["reg"])}


def _with_retry(fn, tries, label):
    """Run fn(), retrying transport-level portal failures with backoff.
    The portal frequently resets connections / 504s; these are transient."""
    delay = 2
    for attempt in range(1, tries + 1):
        try:
            return fn()
        except PortalError as e:
            transient = ("network error" in str(e) or "HTTP 5" in str(e))
            if not transient or attempt == tries:
                raise
            print(f"    {label}: {e} — retry {attempt}/{tries - 1} in {delay}s")
            time.sleep(delay)
            delay *= 2


def list_courses():
    """All courses on the logged-in account (fresh from the portal)."""
    return _with_retry(_session.list_courses, 3, "getcourses")


def open_course(course_code, tries=4):
    return _with_retry(lambda: _session.open_course(course_code),
                       tries, f"open_course {course_code}")


def session_code(unit, session_n):
    return unit * 100 + session_n


def read_slot(course_code, unit, session_n, retries=3):
    """Return {'states':[slo1,slo2], 'links':[url|None, url|None]}."""
    if not _session.course_info or \
            _session.course_info.get("COURSE_CODE") != course_code:
        open_course(course_code)
    res = _with_retry(
        lambda: _session.get_session_status(session_code(unit, session_n)),
        retries, f"read_slot U{unit} S{session_n}")
    practice = res.get("PRACTICE") or {}
    links = res.get("SLOLINK") or {}
    sess = session_code(unit, session_n)
    states, out_links = [], []
    for slo in (1, 2):
        code = f"{sess}{slo}"
        states.append(_PRACTICE_STATE.get(practice.get(code, 0), "?"))
        link = links.get(code)
        # SLOLINK values are {"view": url, "download": url, "fileId": 0}
        if isinstance(link, dict):
            link = link.get("view")
        out_links.append(link)
    return {"states": states, "links": out_links}


def submit_links(course_code, unit, session_n, urls, retries=4):
    """Submit [slo1_url, slo2_url] for one session. True iff all accepted."""
    if not _session.course_info or \
            _session.course_info.get("COURSE_CODE") != course_code:
        open_course(course_code)
    ok_all = True
    for slo, url in enumerate(urls, start=1):
        if not url:
            continue
        ok, msg = _with_retry(
            lambda: _session.submit_link(unit, session_n, slo, url),
            retries, f"submitlink U{unit} S{session_n} SLO{slo}")
        if not ok:
            ok_all = False
            print(f"    submitlink U{unit} S{session_n} SLO{slo} rejected: {msg}")
    return ok_all
