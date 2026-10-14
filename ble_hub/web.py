"""Configuration UI: profiles, Google linking, scale pairing and measurements."""

from __future__ import annotations

import secrets
from datetime import date, datetime
from html import escape
from pathlib import Path
from typing import Any
from urllib.parse import quote

from aiohttp import web

from ble_hub import google_health
from ble_hub.bodycomp import age_on
from ble_hub.hub import Hub

STATIC_DIR = Path(__file__).parent / "static"
HUB_KEY: web.AppKey = web.AppKey("hub", Hub)
LISTENER_KEY: web.AppKey = web.AppKey("listener", object)


def e(value: Any) -> str:
    return escape("" if value is None else str(value), quote=True)


def local_time(iso: str | None) -> str:
    if not iso:
        return "—"
    return datetime.fromisoformat(iso).astimezone().strftime("%a %d %b %Y, %H:%M")


def ago(timestamp: float | None) -> str:
    if not timestamp:
        return "never"
    seconds = int(datetime.now().timestamp() - timestamp)
    if seconds < 90:
        return "just now"
    if seconds < 5400:
        return f"{seconds // 60} min ago"
    if seconds < 172800:
        return f"{seconds // 3600} h ago"
    return f"{seconds // 86400} days ago"


def page(title: str, body: str, *, active: str = "", flash: str | None = None, script: str = "") -> web.Response:
    nav = "".join(
        f'<a href="{href}" class="{"active" if key == active else ""}">{label}</a>'
        for key, href, label in (("home", "/", "Overview"), ("profiles", "/profiles", "Profiles"), ("settings", "/settings", "Settings"))
    )
    notice = f'<div class="flash">{e(flash)}</div>' if flash else ""
    html = f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title)} · Philips BLE Hub</title>
<link rel="stylesheet" href="/static/app.css">
</head><body>
<header class="top"><div class="wrap"><span class="brand">Philips BLE Hub</span><nav>{nav}</nav></div></header>
<main class="wrap">{notice}{body}</main>
{f"<script>{script}</script>" if script else ""}
</body></html>"""
    return web.Response(text=html, content_type="text/html")


def redirect(location: str, flash: str | None = None) -> web.HTTPFound:
    if flash:
        sep = "&" if "?" in location else "?"
        location = f"{location}{sep}flash={quote(flash)}"
    return web.HTTPFound(location)


def hub_of(request: web.Request) -> Hub:
    return request.app[HUB_KEY]


# -- overview -----------------------------------------------------------------

def scale_card(status: dict[str, Any]) -> str:
    if status["pairing"]:
        badge = '<span class="badge warn">Pairing</span>'
        text = (f"Hold the unit button on the scale for 3 seconds until the pairing symbols alternate. "
                f'<span id="pair-left">{status["pairing_seconds_left"]}</span> s left.')
    elif status["paired"]:
        badge = '<span class="badge ok">Paired</span>'
        text = "Step on the scale barefoot. Weighs arrive here automatically."
    else:
        badge = '<span class="badge muted">Not paired</span>'
        text = "Pair the scale once to start receiving weighs."
    state = {"scanning": "Listening", "connected": "Connected", "starting": "Starting", "disabled": "Bluetooth off"}.get(status["state"], status["state"])
    error = f'<p class="error small">{e(status["last_error"])}</p>' if status.get("last_error") else ""
    result = ""
    if status.get("last_pair_result") == "paired":
        result = '<p class="ok small">Paired. You can step on the scale now.</p>'
    elif status.get("last_pair_result") == "failed":
        result = '<p class="error small">Pairing did not complete. Try again.</p>'
    return f"""
<section class="card" id="scale-card">
  <div class="card-head"><h2>Scale</h2>{badge}</div>
  <p>{text}</p>
  <dl class="facts">
    <div><dt>Bluetooth</dt><dd id="scale-state">{e(state)}</dd></div>
    <div><dt>Last contact</dt><dd>{e(ago(status["last_seen"]))}</dd></div>
    <div><dt>Address</dt><dd class="mono">{e(status["address"] or "—")}</dd></div>
  </dl>
  {result}{error}
  <form method="post" action="/scale/pair"><button class="{"secondary" if status["paired"] else "primary"}">{"Pair again" if status["paired"] else "Pair scale"}</button></form>
</section>"""


def profile_select(profiles, selected: int | None, measurement_id: int) -> str:
    options = ['<option value="">Unassigned</option>'] + [
        f'<option value="{p["id"]}"{" selected" if p["id"] == selected else ""}>{e(p["name"])}</option>' for p in profiles
    ]
    return (f'<form method="post" action="/measurements/{measurement_id}/assign" class="inline">'
            f'<select name="profile_id" onchange="this.form.submit()">{"".join(options)}</select>'
            f'<noscript><button class="small">Save</button></noscript></form>')


GOOGLE_LABEL = {"none": ("muted", "Not sent"), "pending": ("warn", "Queued"), "done": ("ok", "Sent"), "error": ("error", "Failed")}


def measurement_rows(rows, profiles) -> str:
    if not rows:
        return '<p class="muted">No weighs yet.</p>'
    body = []
    for row in rows:
        tone, label = GOOGLE_LABEL.get(row["google_status"], ("muted", row["google_status"]))
        title = f' title="{e(row["google_error"])}"' if row["google_error"] else ""
        retry = ""
        if row["google_status"] == "error":
            retry = f'<form method="post" action="/measurements/{row["id"]}/retry" class="inline"><button class="link">Retry</button></form>'
        note = f'<div class="small muted">{e(row["assign_note"])}</div>' if row["profile_id"] is None and row["assign_note"] else ""
        body.append(f"""<tr class="{"needs" if row["profile_id"] is None else ""}">
  <td>{e(local_time(row["measured_at"]))}</td>
  <td class="num">{row["weight_kg"]:.1f} kg</td>
  <td class="num">{f'{row["fat_pct"]:.1f} %' if row["fat_pct"] is not None else "—"}</td>
  <td class="num">{f'{row["lean_kg"]:.1f} kg' if row["lean_kg"] is not None else "—"}</td>
  <td>{profile_select(profiles, row["profile_id"], row["id"])}{note}</td>
  <td><span class="badge {tone}"{title}>{label}</span> {retry}</td>
  <td><form method="post" action="/measurements/{row["id"]}/delete" class="inline" onsubmit="return confirm('Delete this weigh from the hub?')"><button class="link danger">Delete</button></form></td>
</tr>""")
    return f"""<div class="table-wrap"><table>
<thead><tr><th>When</th><th class="num">Weight</th><th class="num">Body fat</th><th class="num">Lean mass</th><th>Person</th><th>Google</th><th></th></tr></thead>
<tbody>{"".join(body)}</tbody></table></div>"""


async def overview(request: web.Request) -> web.Response:
    hub = hub_of(request)
    listener = request.app[LISTENER_KEY]
    status = listener.status()
    profiles = hub.db.profiles()
    rows = hub.db.measurements(50)
    unassigned = [row for row in rows if row["profile_id"] is None]
    setup = []
    if not profiles:
        setup.append('<li><a href="/profiles/new">Add a profile</a> for each person who uses the scale.</li>')
    if not hub.google_client():
        setup.append('<li><a href="/settings">Add your Google OAuth client</a> so profiles can be linked to Google Health.</li>')
    if not status["paired"]:
        setup.append("<li>Pair the scale.</li>")
    setup_html = f'<section class="card note"><h2>Getting started</h2><ol>{"".join(setup)}</ol></section>' if setup else ""
    attention = (f'<p class="warn-text">{len(unassigned)} weigh{"s" if len(unassigned) != 1 else ""} could not be matched to a person. '
                 f"Choose who it was below.</p>") if unassigned else ""
    events = "".join(
        f'<li class="{e(ev["level"])}"><time>{e(local_time(ev["at"]))}</time> {e(ev["message"])}</li>' for ev in hub.db.events(12)
    )
    body = f"""
{setup_html}
<div class="grid">{scale_card(status)}
<section class="card"><div class="card-head"><h2>Activity</h2></div><ul class="events">{events or '<li class="muted">Nothing yet.</li>'}</ul></section></div>
<section class="card"><div class="card-head"><h2>Weighs</h2></div>{attention}{measurement_rows(rows, profiles)}</section>"""
    script = """
const left = document.getElementById('pair-left');
if (left) {
  const timer = setInterval(() => {
    const n = parseInt(left.textContent, 10) - 1;
    left.textContent = Math.max(0, n);
    if (n <= 0) { clearInterval(timer); location.reload(); }
  }, 1000);
}
let lastState = null;
setInterval(async () => {
  try {
    const s = await (await fetch('/api/status')).json();
    if (lastState !== null && s.version !== lastState) location.reload();
    lastState = s.version;
  } catch (err) {}
}, 4000);
"""
    return page("Overview", body, active="home", flash=request.query.get("flash"), script=script)


async def api_status(request: web.Request) -> web.Response:
    hub = hub_of(request)
    status = dict(request.app[LISTENER_KEY].status())
    last = hub.db.conn.execute("SELECT MAX(id) AS id FROM events").fetchone()
    status["version"] = f'{last["id"]}-{status["paired"]}-{status["pairing"]}'
    return web.json_response(status)


async def pair_scale(request: web.Request) -> web.Response:
    request.app[LISTENER_KEY].start_pairing()
    raise redirect("/", "Pairing window open. Hold the unit button on the scale for 3 seconds.")


# -- measurements -----------------------------------------------------------

async def assign_measurement(request: web.Request) -> web.Response:
    hub = hub_of(request)
    form = await request.post()
    raw = str(form.get("profile_id", "")).strip()
    profile_id = int(raw) if raw.isdigit() else None
    measurement_id = int(request.match_info["id"])
    row = hub.db.measurement(measurement_id)
    if row is None:
        raise web.HTTPNotFound()
    hub.assign(measurement_id, profile_id, by="manual", note=None if profile_id else "unassigned by hand")
    message = None
    if row["google_status"] == "done" and row["google_profile_id"] not in (None, profile_id):
        message = "This weigh was already sent to the previous person's Google Health. Delete it there by hand."
    raise redirect("/", message)


async def retry_measurement(request: web.Request) -> web.Response:
    hub = hub_of(request)
    measurement_id = int(request.match_info["id"])
    hub.db.update_measurement(measurement_id, {"google_status": "pending", "google_error": None})
    hub.kick_uploads()
    raise redirect("/", "Upload queued.")


async def delete_measurement(request: web.Request) -> web.Response:
    hub_of(request).db.delete_measurement(int(request.match_info["id"]))
    raise redirect("/", "Weigh deleted from the hub. Anything already sent to Google stays there.")


# -- profiles ----------------------------------------------------------------

def parse_profile(form) -> tuple[dict[str, Any], list[str]]:
    errors = []
    values: dict[str, Any] = {"name": str(form.get("name", "")).strip()}
    if not values["name"]:
        errors.append("Name is required.")
    values["sex"] = str(form.get("sex", ""))
    if values["sex"] not in ("male", "female"):
        errors.append("Choose male or female; the body-fat equation needs it.")
    try:
        birth = date.fromisoformat(str(form.get("birth_date", "")))
        values["birth_date"] = birth.isoformat()
        if not 16 <= age_on(birth, date.today()) <= 100:
            errors.append("Age must be between 16 and 100.")
    except ValueError:
        errors.append("Birth date is required.")
    try:
        values["height_cm"] = float(str(form.get("height_cm", "")).replace(",", "."))
        if not 100 <= values["height_cm"] <= 230:
            errors.append("Height must be between 100 and 230 cm.")
    except ValueError:
        errors.append("Height is required.")
    raw_weight = str(form.get("start_weight_kg", "")).strip().replace(",", ".")
    if raw_weight:
        try:
            values["start_weight_kg"] = float(raw_weight)
            if not 20 <= values["start_weight_kg"] <= 300:
                errors.append("Current weight must be between 20 and 300 kg.")
        except ValueError:
            errors.append("Current weight must be a number.")
    else:
        values["start_weight_kg"] = None
    return values, errors


def profile_form(values: dict[str, Any], errors: list[str], action: str, submit: str) -> str:
    error_html = "".join(f"<li>{e(err)}</li>" for err in errors)
    sex = values.get("sex")
    return f"""
<form method="post" action="{e(action)}" class="stack">
  {f'<ul class="errors">{error_html}</ul>' if errors else ""}
  <label>Name<input name="name" required maxlength="40" value="{e(values.get("name"))}"></label>
  <fieldset><legend>Sex</legend>
    <label class="choice"><input type="radio" name="sex" value="male"{" checked" if sex == "male" else ""}> Male</label>
    <label class="choice"><input type="radio" name="sex" value="female"{" checked" if sex == "female" else ""}> Female</label>
  </fieldset>
  <div class="row">
    <label>Birth date<input type="date" name="birth_date" required value="{e(values.get("birth_date"))}"></label>
    <label>Height (cm)<input name="height_cm" inputmode="decimal" required value="{e(values.get("height_cm"))}"></label>
  </div>
  <label>Current weight (kg)<input name="start_weight_kg" inputmode="decimal" value="{e(values.get("start_weight_kg") or "")}">
    <span class="hint">Used to recognise this person's first weighs. After that the hub uses their recent weighs.</span></label>
  <div class="actions"><button class="primary">{e(submit)}</button><a href="/profiles" class="button secondary">Cancel</a></div>
</form>"""


async def profiles_page(request: web.Request) -> web.Response:
    hub = hub_of(request)
    profiles = hub.db.profiles()
    refs = hub.references()
    cards = []
    for p in profiles:
        age = age_on(date.fromisoformat(p["birth_date"]), date.today())
        ref = refs.get(p["id"])
        if p["google_linked"]:
            google = '<span class="badge ok">Google linked</span>'
            if p["google_last_error"]:
                google = f'<span class="badge error" title="{e(p["google_last_error"])}">Google error</span>'
        else:
            google = '<span class="badge muted">No Google account</span>'
        cards.append(f"""
<section class="card profile">
  <div class="card-head"><h2>{e(p["name"])}</h2>{google}</div>
  <p class="muted">{e(p["sex"].capitalize())}, {age} years, {p["height_cm"]:g} cm · recognised around {f"{ref:.1f} kg" if ref else "—"}</p>
  {f'<p class="error small">{e(p["google_last_error"])}</p>' if p["google_last_error"] else ""}
  <div class="actions">
    <a class="button secondary" href="/profiles/{p["id"]}/edit">Edit</a>
    {f'<form method="post" action="/profiles/{p["id"]}/google/unlink" class="inline" onsubmit="return confirm(&quot;Unlink this Google account?&quot;)"><button class="secondary">Unlink Google</button></form>'
     if p["google_linked"] else f'<a class="button primary" href="/profiles/{p["id"]}/google">Link Google account</a>'}
  </div>
</section>""")
    body = f"""<div class="page-head"><h1>Profiles</h1><a class="button primary" href="/profiles/new">Add profile</a></div>
{"".join(cards) or '<p class="muted">No profiles yet. Add one for each person who uses the scale.</p>'}"""
    return page("Profiles", body, active="profiles", flash=request.query.get("flash"))


async def new_profile(request: web.Request) -> web.Response:
    hub = hub_of(request)
    if request.method == "POST":
        values, errors = parse_profile(await request.post())
        if not errors:
            hub.db.create_profile(values)
            raise redirect("/profiles", f"Added {values['name']}.")
    else:
        values, errors = {}, []
    return page("Add profile", f"<h1>Add profile</h1>{profile_form(values, errors, '/profiles/new', 'Add profile')}", active="profiles")


async def edit_profile(request: web.Request) -> web.Response:
    hub = hub_of(request)
    profile_id = int(request.match_info["id"])
    profile = hub.db.profile(profile_id)
    if profile is None:
        raise web.HTTPNotFound()
    if request.method == "POST":
        values, errors = parse_profile(await request.post())
        if not errors:
            hub.db.update_profile(profile_id, values)
            hub.recompute_profile(profile_id)
            raise redirect("/profiles", f"Saved {values['name']}.")
    else:
        values, errors = dict(profile), []
    delete = f"""<form method="post" action="/profiles/{profile_id}/delete" class="danger-zone" onsubmit="return confirm('Delete this profile? Its weighs become unassigned.')">
<button class="link danger">Delete profile</button></form>"""
    return page("Edit profile", f"<h1>Edit {e(profile['name'])}</h1>{profile_form(values, errors, f'/profiles/{profile_id}/edit', 'Save')}{delete}", active="profiles")


async def delete_profile(request: web.Request) -> web.Response:
    hub_of(request).db.delete_profile(int(request.match_info["id"]))
    raise redirect("/profiles", "Profile deleted.")


# -- google linking ------------------------------------------------------------

async def google_link_page(request: web.Request) -> web.Response:
    hub = hub_of(request)
    profile_id = int(request.match_info["id"])
    profile = hub.db.profile(profile_id)
    if profile is None:
        raise web.HTTPNotFound()
    client = hub.google_client()
    if client is None:
        raise redirect("/settings", "Add your Google OAuth client first.")
    pending = hub.db.oauth_pending_for(profile_id)
    if pending is None or request.query.get("new"):
        verifier, challenge = google_health.new_pkce()
        state = secrets.token_urlsafe(24)
        hub.db.add_oauth_pending(state, profile_id, verifier)
    else:
        state, verifier = pending["state"], pending["verifier"]
        challenge = google_health.pkce_challenge(verifier)
    url = google_health.authorization_url(client[0], state, challenge)
    error = request.query.get("error")
    body = f"""<h1>Link Google account for {e(profile['name'])}</h1>
<section class="card stack">
  {f'<p class="error">{e(error)}</p>' if error else ""}
  <ol class="steps">
    <li><a class="button primary" href="{e(url)}" target="_blank" rel="noopener">Sign in with Google</a>
      <span class="hint">Use {e(profile['name'])}'s Google account and allow access to health measurements.</span></li>
    <li>Google then sends the browser to an address starting with <code>http://localhost/?state=…</code>.
      That page will not load. This is expected.</li>
    <li>Copy that whole address from the address bar and paste it here.</li>
  </ol>
  <form method="post" action="/profiles/{profile_id}/google" class="stack">
    <label>Address after signing in<input name="redirect" required placeholder="http://localhost/?state=…&amp;code=…" autocomplete="off"></label>
    <div class="actions"><button class="primary">Link account</button><a class="button secondary" href="/profiles">Cancel</a></div>
  </form>
</section>"""
    return page("Link Google", body, active="profiles")


async def google_link_finish(request: web.Request) -> web.Response:
    hub = hub_of(request)
    profile_id = int(request.match_info["id"])
    form = await request.post()
    client = hub.google_client()
    try:
        code, state = google_health.parse_redirect(str(form.get("redirect", "")))
        pending = hub.db.take_oauth_pending(state) if state else hub.db.oauth_pending_for(profile_id)
        if pending is None or pending["profile_id"] != profile_id:
            raise google_health.GoogleError("That sign-in belongs to a different or expired request. Start again.")
        if state is None:
            hub.db.take_oauth_pending(pending["state"])
        tokens = await google_health.exchange_code(
            await hub.http(), client_id=client[0], client_secret=client[1], code=code, verifier=pending["verifier"]
        )
    except google_health.GoogleError as exc:
        raise web.HTTPFound(f"/profiles/{profile_id}/google?new=1&error={quote(str(exc))}")
    hub.db.save_google_link(profile_id, tokens["refresh_token"], tokens.get("access_token"), tokens.get("expires_at"))
    hub.db.log(f"Linked a Google account to {hub.db.profile(profile_id)['name']}")
    for row in hub.db.conn.execute("SELECT id FROM measurements WHERE profile_id = ? AND google_status = 'none'", (profile_id,)).fetchall():
        hub.db.update_measurement(row["id"], {"google_status": "pending"})
    hub.kick_uploads()
    raise redirect("/profiles", "Google account linked. Earlier weighs for this person are being sent.")


async def google_unlink(request: web.Request) -> web.Response:
    hub = hub_of(request)
    hub.db.delete_google_link(int(request.match_info["id"]))
    raise redirect("/profiles", "Google account unlinked. Remove the app's access in that Google account as well.")


# -- settings --------------------------------------------------------------------

async def settings_page(request: web.Request) -> web.Response:
    hub = hub_of(request)
    if request.method == "POST":
        form = await request.post()
        client_id = str(form.get("google_client_id", "")).strip()
        secret = str(form.get("google_client_secret", "")).strip()
        tolerance = str(form.get("assign_tolerance_kg", "")).strip().replace(",", ".")
        hub.db.set_setting("google_client_id", client_id or None)
        if secret:
            hub.db.set_setting("google_client_secret", secret)
        try:
            if 0.5 <= float(tolerance) <= 15:
                hub.db.set_setting("assign_tolerance_kg", tolerance)
        except ValueError:
            pass
        raise redirect("/settings", "Settings saved.")
    has_secret = bool(hub.db.get_setting("google_client_secret"))
    body = f"""<h1>Settings</h1>
<section class="card stack">
  <h2>Google Health</h2>
  <p>Each person's weighs go to their own Google account through the Google Health API. The hub needs one OAuth client, created once:</p>
  <ol class="steps">
    <li>In the <a href="https://console.cloud.google.com/" target="_blank" rel="noopener">Google Cloud console</a>, create a project and enable the <strong>Google Health API</strong>.</li>
    <li>Set up the OAuth consent screen (External) and add the scope <code>{e(google_health.SCOPE.rsplit("/", 1)[1])}</code>.
      While the app is in <em>Testing</em>, add every person as a test user. Google ends test-mode sign-ins after 7 days, so publish the app for continuous syncing.</li>
    <li>Create an OAuth client ID of type <strong>Desktop app</strong> and paste its ID and secret here.</li>
  </ol>
  <form method="post" action="/settings" class="stack">
    <label>Client ID<input name="google_client_id" value="{e(hub.db.get_setting("google_client_id"))}" autocomplete="off"></label>
    <label>Client secret<input name="google_client_secret" type="password" placeholder="{"Saved. Leave empty to keep it" if has_secret else ""}" autocomplete="off"></label>
    <h2>Recognising people</h2>
    <label>Match weighs within (kg)<input name="assign_tolerance_kg" inputmode="decimal" value="{e(hub.tolerance())}">
      <span class="hint">A weigh goes to the person whose recent weight is closest, if it is within this range and clearly closer than anyone else. Otherwise you choose.</span></label>
    <div class="actions"><button class="primary">Save settings</button></div>
  </form>
</section>
<section class="card"><h2>Body composition</h2>
<p>Body fat is calculated per person from the scale's impedance with the Jebb et al. (2000) equation for foot-to-foot scales. Typical individual error is about ±4.8 % for men and ±3.3 % for women. Lean mass is weight minus fat. The scale's own body-fat figure is stored but not used.</p></section>"""
    return page("Settings", body, active="settings", flash=request.query.get("flash"))


def create_app(hub: Hub, listener: Any) -> web.Application:
    app = web.Application()
    app[HUB_KEY] = hub
    app[LISTENER_KEY] = listener
    app.router.add_get("/", overview)
    app.router.add_get("/api/status", api_status)
    app.router.add_post("/scale/pair", pair_scale)
    app.router.add_post("/measurements/{id:\\d+}/assign", assign_measurement)
    app.router.add_post("/measurements/{id:\\d+}/retry", retry_measurement)
    app.router.add_post("/measurements/{id:\\d+}/delete", delete_measurement)
    app.router.add_get("/profiles", profiles_page)
    app.router.add_route("*", "/profiles/new", new_profile)
    app.router.add_route("*", "/profiles/{id:\\d+}/edit", edit_profile)
    app.router.add_post("/profiles/{id:\\d+}/delete", delete_profile)
    app.router.add_get("/profiles/{id:\\d+}/google", google_link_page)
    app.router.add_post("/profiles/{id:\\d+}/google", google_link_finish)
    app.router.add_post("/profiles/{id:\\d+}/google/unlink", google_unlink)
    app.router.add_route("*", "/settings", settings_page)
    app.router.add_static("/static", STATIC_DIR)
    return app
