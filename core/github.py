"""GitHub hosting via the REST Contents API — no local git needed.

Token: a user's personal access token (repo scope). One shared repo holds
all students' PDFs under <course>/<reg>/<code>_solved.pdf so the same PDF
for different users never collides and re-push for a new user is instant
(content-addressed by path, updated only when bytes differ).
"""
import base64, json, urllib.request, urllib.error

API = "https://api.github.com"

def _req(method, url, token, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(API + url, data=data, method=method, headers={
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
        "Content-Type": "application/json",
        "User-Agent": "ecurricula-bot",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        body = e.read()[:300]
        try:
            return e.code, json.loads(body)
        except Exception:
            return e.code, {"raw": body.decode(errors="replace")}

def whoami(token):
    status, d = _req("GET", "/user", token)
    if status == 200:
        return d["login"]
    raise RuntimeError(f"GitHub auth failed ({status}): {d.get('message')}")

def ensure_repo(token, owner, repo):
    status, _ = _req("GET", f"/repos/{owner}/{repo}", token)
    if status == 200:
        return True
    status, d = _req("POST", "/user/repos", token,
                     {"name": repo, "private": False, "description": "Solved course worksheets"})
    if status in (200, 201):
        return True
    raise RuntimeError(f"Cannot create repo {owner}/{repo} ({status}): {d.get('message')}")

def push_file(token, owner, repo, local_path, remote_path, message=None):
    """Create-or-update a file. Returns the github.com blob URL."""
    with open(local_path, "rb") as f:
        content = base64.b64encode(f.read()).decode()
    # fetch existing sha (required for update; also lets us skip unchanged files)
    status, d = _req("GET", f"/repos/{owner}/{repo}/contents/{remote_path}", token)
    sha = d.get("sha") if status == 200 else None
    if sha and d.get("content") and d["content"].replace("\n", "") == content:
        return d["html_url"]  # unchanged
    payload = {"message": message or f"worksheet {remote_path}", "content": content}
    if sha:
        payload["sha"] = sha
    status, d = _req("PUT", f"/repos/{owner}/{repo}/contents/{remote_path}", token, payload)
    if status in (200, 201):
        return d["content"]["html_url"]
    raise RuntimeError(f"Push failed for {remote_path} ({status}): {d.get('message')}")
