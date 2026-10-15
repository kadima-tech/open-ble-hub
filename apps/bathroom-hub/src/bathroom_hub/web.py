"""Web UI: onboarding, dashboard, device hub, people, Google linking and settings.

Server-rendered HTML in the Mineral design (see DESIGN.md). Every action is a
form POST followed by a redirect; ``static/app.js`` only adds polling, the
pairing countdown, confirmations and auto-submitting selects.
"""

from __future__ import annotations

import secrets
from datetime import UTC, date, datetime, timedelta
from html import escape
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode

from aiohttp import web

from bathroom_hub import charts, devices, google_health
from bathroom_hub.bodycomp import age_on
from bathroom_hub.hub import Hub

STATIC_DIR = Path(__file__).parent / "static"
HUB_KEY: web.AppKey = web.AppKey("hub", Hub)
LISTENER_KEY: web.AppKey = web.AppKey("listener", object)
PROFILE_COOKIE = "profile"
RANGES = (("7", "7d", 7), ("30", "30d", 30), ("90", "90d", 90), ("365", "1y", 365))
FAT_ERROR = {"male": 4.8, "female": 3.3}
ARIA_PAGE = ' aria-current="page"'
ARIA_TRUE = ' aria-current="true"'

ICONS = {
    "back": '<path d="M15 5l-7 7 7 7"/>',
    "next": '<path d="M9 5l7 7-7 7"/>',
    "down": '<path d="M6 9l6 6 6-6"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "check": '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
    "search": '<circle cx="11" cy="11" r="6.5"/><path d="M16 16l4 4"/>',
    "devices": '<rect x="4" y="5" width="16" height="14" rx="3"/><path d="M9 10.5c1.7-1.6 4.3-1.6 6 0"/><circle cx="12" cy="13.6" r=".9"/>',
    "settings": (
        '<path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38'
        'a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73'
        'l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25'
        'a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74'
        'l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"/>'
        '<circle cx="12" cy="12" r="3"/>'
    ),
    "hub": '<rect x="4" y="6" width="16" height="12" rx="2"/><path d="M8 18v2M16 18v2M8 10h3M8 13h5"/>',
    "scale": '<rect x="3" y="3" width="18" height="18" rx="5"/><rect x="8" y="6.5" width="8" height="4" rx="1.2"/>',
    "brush": '<rect x="9" y="2.5" width="6" height="19" rx="3"/><path d="M12 2.5v4"/>',
    "people": '<circle cx="9" cy="9" r="3.5"/><path d="M3 19c1-3.5 3.5-5 6-5s5 1.5 6 5"/><circle cx="17" cy="8" r="2.5"/><path d="M16 13.5c2.5 0 4.2 1.4 5 4.5"/>',
    "cloud": '<path d="M7 18h10a4 4 0 0 0 .5-8A6 6 0 0 0 6 9.5 4.3 4.3 0 0 0 7 18z"/>',
    "alert": '<path d="M12 4l9 16H3z"/><path d="M12 10v4M12 17v.1"/>',
    "help": '<circle cx="12" cy="12" r="8.5"/><path d="M9.6 9.5a2.5 2.5 0 1 1 3.2 2.4c-.6.2-.8.6-.8 1.3M12 16.3v.1"/>',
}
CATEGORY_ICON = {"Scales": "scale", "Oral care": "brush"}


# -- small helpers ---------------------------------------------------------------


def e(value: Any) -> str:
    return escape("" if value is None else str(value), quote=True)


def icon(name: str, size: int = 20, label: str | None = None) -> str:
    aria = f'role="img" aria-label="{e(label)}"' if label else 'aria-hidden="true"'
    return (
        f'<svg class="icon" width="{size}" height="{size}" viewBox="0 0 24 24" {aria} fill="none" stroke="currentColor" '
        f'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">{ICONS[name]}</svg>'
    )


def local(iso: str) -> datetime:
    return datetime.fromisoformat(iso).astimezone()


def when(iso: str | None) -> str:
    """'Today 07:42', 'Yesterday 22:10', 'Sun 07:41', '12 Oct', '12 Oct 2025'."""
    if not iso:
        return "—"
    moment = local(iso)
    today = datetime.now().astimezone().date()
    days = (today - moment.date()).days
    clock = moment.strftime("%H:%M")
    if days == 0:
        return f"Today {clock}"
    if days == 1:
        return f"Yesterday {clock}"
    if 1 < days < 7:
        return f"{moment.strftime('%a')} {clock}"
    if moment.year == today.year:
        return f"{moment.day} {moment.strftime('%b')}"
    return f"{moment.day} {moment.strftime('%b %Y')}"


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


def kg(value: float | None) -> str:
    return "—" if value is None else f"{value:.1f}"


def signed(value: float) -> str:
    return f"{'+' if value > 0 else '−' if value < 0 else '±'}{abs(value):.1f}"


def safe_next(value: Any, default: str = "/") -> str:
    target = str(value or "")
    return target if target.startswith("/") and not target.startswith("//") else default


def with_query(path: str, **params: Any) -> str:
    clean = {key: value for key, value in params.items() if value not in (None, "")}
    return f"{path}?{urlencode(clean)}" if clean else path


def avatar(profile, size: str = "") -> str:
    return f'<span class="avatar av-{profile["id"] % 5} {size}" aria-hidden="true">{e(profile["name"][:1].upper())}</span>'


def profile_meta(profile) -> str:
    age = age_on(date.fromisoformat(profile["birth_date"]), date.today())
    return f'{profile["sex"].capitalize()} · {age} · {profile["height_cm"]:g} cm'


def badge(text: str, tone: str = "muted") -> str:
    return f'<span class="badge {tone}">{e(text)}</span>'


def page(
    title: str,
    body: str,
    *,
    flash: str | None = None,
    poll: bool = False,
    width: str = "",
) -> web.Response:
    notice = (
        f'<div class="flash" role="status">{icon("check", 18)}<span>{e(flash)}</span></div>'
        if flash
        else ""
    )
    html = f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="theme-color" content="#EEF1EC" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#111613" media="(prefers-color-scheme: dark)">
<title>{e(title)} · Bathroom Hub</title>
<link rel="icon" href="/static/icon.svg" type="image/svg+xml">
<link rel="stylesheet" href="/static/app.css">
<script src="/static/app.js" defer></script>
</head><body{' data-poll="1"' if poll else ""}>
<main class="shell {width}">{notice}{body}</main>
</body></html>"""
    return web.Response(text=html, content_type="text/html")


def redirect(location: str, flash: str | None = None) -> web.HTTPFound:
    if flash:
        sep = "&" if "?" in location else "?"
        location = f"{location}{sep}flash={quote(flash)}"
    return web.HTTPFound(location)


def hub_of(request: web.Request) -> Hub:
    return request.app[HUB_KEY]


def status_of(request: web.Request) -> dict[str, Any]:
    return request.app[LISTENER_KEY].status()


def topbar(
    title: str, back: str | None = None, sub: str = "", actions: str = ""
) -> str:
    back_html = (
        f'<a class="icon-btn" href="{e(back)}" aria-label="Back">{icon("back")}</a>'
        if back
        else ""
    )
    sub_html = f'<p class="sub">{sub}</p>' if sub else ""
    return f"""<header class="topbar">{back_html}<div class="topbar-title"><h1>{e(title)}</h1>{sub_html}</div>{actions}</header>"""


def current_profile(request: web.Request, profiles) -> Any:
    wanted = request.query.get("p") or request.cookies.get(PROFILE_COOKIE)
    for profile in profiles:
        if str(profile["id"]) == wanted:
            return profile
    latest = (
        request.app[HUB_KEY]
        .db.conn.execute(
            "SELECT profile_id FROM measurements WHERE profile_id IS NOT NULL ORDER BY measured_at DESC LIMIT 1"
        )
        .fetchone()
    )
    for profile in profiles:
        if latest and profile["id"] == latest["profile_id"]:
            return profile
    return profiles[0] if profiles else None


def remember(response: web.Response, profile) -> web.Response:
    if profile is not None:
        response.set_cookie(
            PROFILE_COOKIE,
            str(profile["id"]),
            max_age=365 * 86400,
            samesite="Lax",
            httponly=True,
        )
    return response


# -- dashboard -------------------------------------------------------------------


def profile_switcher(current, profiles) -> str:
    items = "".join(
        f'<a href="/?p={p["id"]}" class="menu-item{" is-current" if p["id"] == current["id"] else ""}"'
        f'{ARIA_TRUE if p["id"] == current["id"] else ""}>{avatar(p, "sm")}<span>{e(p["name"])}</span></a>'
        for p in profiles
    )
    return f"""<details class="switcher">
<summary>{avatar(current)}<span class="switcher-text"><strong>{e(current["name"])}</strong><small>{e(profile_meta(current))}</small></span>{icon("down", 16)}</summary>
<div class="menu" role="menu">{items}
<a href="/profiles/new" class="menu-item">{icon("plus", 18)}<span>Add person</span></a>
<a href="/profiles" class="menu-item">{icon("people", 18)}<span>Manage people</span></a>
</div></details>"""


def who_card(hub: Hub, profiles, refs, next_url: str) -> str:
    pending = hub.db.unassigned()
    if not pending:
        return ""
    row = pending[0]
    buttons = []
    for p in profiles:
        ref = refs.get(p["id"])
        hint = (
            f"usually {ref:.1f} kg ({signed(row['weight_kg'] - ref)})"
            if ref
            else "no weighs yet"
        )
        buttons.append(
            f'<button name="profile_id" value="{p["id"]}" class="who-option">{avatar(p, "sm")}'
            f'<span><strong>{e(p["name"])}</strong><small>{e(hint)}</small></span></button>'
        )
    more = (
        f'<a href="/history?view=unassigned" class="link-small">{len(pending) - 1} more waiting</a>'
        if len(pending) > 1
        else ""
    )
    return f"""<section class="card notice" aria-labelledby="who">
<div class="card-head"><h2 id="who">Who was this?</h2><span class="muted-small">{e(when(row["measured_at"]))}</span></div>
<p class="who-weight"><strong>{row["weight_kg"]:.1f} kg</strong> could not be matched to one person. Nothing is sent until you choose.</p>
<form method="post" action="/measurements/{row["id"]}/assign" class="who-options">
<input type="hidden" name="next" value="{e(next_url)}">{"".join(buttons)}</form>
<div class="card-foot">
<form method="post" action="/measurements/{row["id"]}/delete" data-confirm="Delete this weigh? Use this when nobody really stepped on.">
<input type="hidden" name="next" value="{e(next_url)}"><button class="btn-link">Not a real weigh</button></form>{more}</div>
</section>"""


def google_row(hub: Hub, profile) -> str:
    link = hub.db.google_link(profile["id"])
    if link is None:
        text, tone = ("Not connected", "muted")
        action = f'<a class="btn btn-secondary btn-sm" href="/profiles/{profile["id"]}/google?next=/">Connect</a>'
    elif link["last_error"]:
        text, tone = ("Needs attention: " + link["last_error"], "error")
        action = f'<a class="btn btn-secondary btn-sm" href="/profiles/{profile["id"]}/google?new=1&amp;next=/">Reconnect</a>'
    else:
        text = (
            f'Last sent {when(link["last_ok_at"])}'
            if link["last_ok_at"]
            else "Connected · nothing sent yet"
        )
        tone, action = "ok", ""
    return f"""<div class="row-item"><span class="icon-tile {tone}">{icon("cloud", 18)}</span>
<div class="row-text"><strong>Google Health</strong><small class="{tone}-text">{e(text)}</small></div>{action}</div>"""


async def dashboard(request: web.Request) -> web.Response:
    hub = hub_of(request)
    profiles = hub.db.profiles()
    if not profiles:
        raise web.HTTPFound("/welcome")
    profile = current_profile(request, profiles)
    status = status_of(request)
    range_key = request.query.get("range", "30")
    days = next((d for key, _, d in RANGES if key == range_key), 30)
    end = datetime.now(UTC)
    start = end - timedelta(days=days)
    rows = hub.db.profile_measurements(
        profile["id"], since=start.isoformat(timespec="seconds")
    )
    oldest_first = list(reversed(rows))
    latest = hub.db.profile_measurements(profile["id"], limit=1)
    latest = latest[0] if latest else None
    refs = hub.references()

    weight_points = [
        (datetime.fromisoformat(r["measured_at"]), r["weight_kg"]) for r in oldest_first
    ]
    fat_points = [
        (datetime.fromisoformat(r["measured_at"]), r["fat_pct"])
        for r in oldest_first
        if r["fat_pct"] is not None
    ]
    lean_points = [
        (datetime.fromisoformat(r["measured_at"]), r["lean_kg"])
        for r in oldest_first
        if r["lean_kg"] is not None
    ]
    latest_comp = next((r for r in rows if r["fat_pct"] is not None), None)

    if latest is None:
        weight_card = f"""<section class="card" aria-labelledby="w"><h2 id="w" class="eyebrow">Weight</h2>
<div class="empty"><p><strong>No weighs for {e(profile["name"])} yet.</strong></p>
<p>Step on the scale barefoot. The weigh appears here within a few seconds.</p></div></section>"""
    else:
        delta = ""
        if len(weight_points) >= 2:
            change = weight_points[-1][1] - weight_points[0][1]
            delta = f'<span class="delta">{signed(change)} kg in {days} days</span>'
        chart = (
            charts.line_chart(
                weight_points,
                start=start,
                end=end,
                tone="weight",
                label=e(
                    f"Weight over {days} days, {len(weight_points)} weighs, latest {latest['weight_kg']:.1f} kg"
                ),
            )
            or '<p class="chart-empty">Weigh a few more times to see a trend.</p>'
        )
        tabs = "".join(
            f'<a href="/?range={key}" class="seg-item{" is-on" if key == range_key else ""}"'
            f'{ARIA_PAGE if key == range_key else ""}>{label}</a>'
            for key, label, _ in RANGES
        )
        start_label = local(start.isoformat()).strftime("%-d %b")
        weight_card = f"""<section class="card" aria-labelledby="w">
<div class="card-head"><h2 id="w" class="eyebrow">Weight · {e(when(latest["measured_at"]))}</h2>{delta}</div>
<p class="big-number">{latest["weight_kg"]:.1f}<span class="unit">kg</span></p>
{chart}
<div class="chart-x" aria-hidden="true"><span>{e(start_label)}</span><span>Today</span></div>
<nav class="seg" aria-label="Time range">{tabs}</nav>
</section>"""

    error = FAT_ERROR[profile["sex"]]
    if latest_comp is None:
        comp_cards = """<section class="card small-card"><h2 class="eyebrow">Body fat</h2><p class="muted-small">Needs a barefoot weigh. The scale measures impedance through your feet.</p></section>
<section class="card small-card"><h2 class="eyebrow">Lean mass</h2><p class="muted-small">Calculated from weight and body fat.</p></section>"""
    else:
        comp_cards = f"""<section class="card small-card" aria-labelledby="fat"><h2 id="fat" class="eyebrow">Body fat</h2>
<p class="mid-number">{latest_comp["fat_pct"]:.1f}<span class="unit">%</span></p>
{charts.sparkline(fat_points, start=start, end=end, tone="fat", min_span=1.0)}
<p class="muted-small">Estimate, ±{error:g} %</p></section>
<section class="card small-card" aria-labelledby="lean"><h2 id="lean" class="eyebrow">Lean mass</h2>
<p class="mid-number">{latest_comp["lean_kg"]:.1f}<span class="unit">kg</span></p>
{charts.sparkline(lean_points, start=start, end=end, tone="lean", min_span=1.0)}
<p class="muted-small">BMI {latest_comp["bmi"]:.1f}</p></section>"""

    recent = hub.db.profile_measurements(profile["id"], limit=5)
    recent_rows = "".join(
        f"""<li class="row-item"><div class="row-text"><strong>{r["weight_kg"]:.1f} kg</strong><small>{e(when(r["measured_at"]))}{f' · {r["fat_pct"]:.1f} % fat' if r["fat_pct"] is not None else ""}</small></div>{google_badge(r)}</li>"""
        for r in recent
    )
    recent_card = (
        f"""<section class="card list-card" aria-labelledby="recent">
<div class="card-head"><h2 id="recent" class="eyebrow">Recent weighs</h2><a href="/history" class="link-small">All weighs</a></div>
<ul class="rows">{recent_rows}</ul></section>"""
        if recent
        else ""
    )

    hub_devices = devices.hub_devices(status, hub.db)
    if hub_devices:
        dev_text = (
            f'{len(hub_devices)} device{"s" if len(hub_devices) != 1 else ""} · '
            + ("listening" if status["state"] != "disabled" else "Bluetooth off")
        )
        dev_tone = "ok" if all(d["state"] == "online" for d in hub_devices) else "warn"
    else:
        dev_text, dev_tone = "No devices yet. Pair your scale.", "warn"
    connections = f"""<section class="card list-card" aria-label="Connections">
{google_row(hub, profile)}
<a href="/devices" class="row-item row-link"><span class="icon-tile {dev_tone}">{icon("devices", 18)}</span>
<div class="row-text"><strong>Device hub</strong><small>{e(dev_text)}</small></div>{icon("next", 18)}</a>
</section>"""

    actions = (
        f'<div class="topbar-actions"><a class="icon-btn" href="/devices" aria-label="Device hub">{icon("devices")}</a>'
        f'<a class="icon-btn" href="/settings" aria-label="Settings">{icon("settings")}</a></div>'
    )
    body = f"""<header class="topbar dash-top">{profile_switcher(profile, profiles)}{actions}</header>
<div class="dash">
<div class="dash-main">{who_card(hub, profiles, refs, "/")}{weight_card}<div class="pair">{comp_cards}</div></div>
<div class="dash-side">{connections}{recent_card}</div>
</div>"""
    return remember(
        page(
            profile["name"],
            body,
            flash=request.query.get("flash"),
            poll=True,
            width="wide",
        ),
        profile,
    )


def google_badge(row) -> str:
    status = row["google_status"]
    if status == "done":
        return badge("Sent", "ok")
    if status == "pending":
        return badge("Queued", "warn")
    if status == "error":
        return (
            f'<span class="badge error" title="{e(row["google_error"])}">Failed</span>'
        )
    return badge("Not sent")


# -- history -------------------------------------------------------------------------


async def history(request: web.Request) -> web.Response:
    hub = hub_of(request)
    profiles = hub.db.profiles()
    if not profiles:
        raise web.HTTPFound("/welcome")
    profile = current_profile(request, profiles)
    view = request.query.get("view", "person")
    if view == "unassigned":
        rows = hub.db.unassigned()
    elif view == "all":
        rows = hub.db.measurements(200)
    else:
        rows = hub.db.profile_measurements(profile["id"], limit=200)
    next_url = with_query("/history", view=view)
    chips = "".join(
        f'<a href="/history?view={key}" class="chip{" is-on" if key == view else ""}"{ARIA_PAGE if key == view else ""}>{e(label)}</a>'
        for key, label in (
            ("person", profile["name"]),
            ("all", "Everyone"),
            ("unassigned", "Needs a person"),
        )
    )
    items = []
    for r in rows:
        options = ['<option value="">Nobody</option>'] + [
            f'<option value="{p["id"]}"{" selected" if p["id"] == r["profile_id"] else ""}>{e(p["name"])}</option>'
            for p in profiles
        ]
        retry = ""
        if r["google_status"] == "error":
            retry = (
                f'<form method="post" action="/measurements/{r["id"]}/retry"><input type="hidden" name="next" value="{e(next_url)}">'
                f'<button class="btn-link">Retry upload</button></form>'
            )
        detail = []
        if r["fat_pct"] is not None:
            detail.append(f'{r["fat_pct"]:.1f} % fat · {r["lean_kg"]:.1f} kg lean')
        if r["profile_id"] is None and r["assign_note"]:
            detail.append(r["assign_note"])
        items.append(f"""<li class="history-item{" needs" if r["profile_id"] is None else ""}">
<div class="history-main"><strong>{r["weight_kg"]:.1f} kg</strong><small>{e(when(r["measured_at"]))}</small>{f'<small>{e(" · ".join(detail))}</small>' if detail else ""}</div>
<div class="history-side">{google_badge(r)}{retry}</div>
<div class="history-actions">
<form method="post" action="/measurements/{r["id"]}/assign" class="inline-form"><input type="hidden" name="next" value="{e(next_url)}">
<label class="sr-only" for="who-{r["id"]}">Person</label>
<select id="who-{r["id"]}" name="profile_id" data-autosubmit>{"".join(options)}</select><noscript><button class="btn btn-secondary btn-sm">Save</button></noscript></form>
<form method="post" action="/measurements/{r["id"]}/delete" data-confirm="Delete this weigh from the hub? Anything already sent to Google stays there.">
<input type="hidden" name="next" value="{e(next_url)}"><button class="btn-link danger">Delete</button></form>
</div></li>""")
    listing = (
        f'<ul class="history">{"".join(items)}</ul>'
        if items
        else '<div class="card empty"><p>No weighs here.</p></div>'
    )
    body = f"""{topbar("Weighs", back="/")}
<nav class="chips" aria-label="Show">{chips}</nav>
{listing}"""
    return page("Weighs", body, flash=request.query.get("flash"))


async def assign_measurement(request: web.Request) -> web.Response:
    hub = hub_of(request)
    form = await request.post()
    raw = str(form.get("profile_id", "")).strip()
    profile_id = int(raw) if raw.isdigit() else None
    measurement_id = int(request.match_info["id"])
    row = hub.db.measurement(measurement_id)
    if row is None:
        raise web.HTTPNotFound()
    if profile_id is not None and hub.db.profile(profile_id) is None:
        raise web.HTTPBadRequest()
    hub.assign(
        measurement_id,
        profile_id,
        by="manual",
        note=None if profile_id else "unassigned by hand",
    )
    message = "Saved."
    if row["google_status"] == "done" and row["google_profile_id"] not in (
        None,
        profile_id,
    ):
        message = "Saved. It was already sent to the previous person's Google Health; delete it there by hand."
    raise redirect(safe_next(form.get("next")), message)


async def retry_measurement(request: web.Request) -> web.Response:
    hub = hub_of(request)
    form = await request.post()
    hub.db.update_measurement(
        int(request.match_info["id"]),
        {"google_status": "pending", "google_error": None},
    )
    hub.kick_uploads()
    raise redirect(safe_next(form.get("next")), "Upload queued.")


async def delete_measurement(request: web.Request) -> web.Response:
    form = await request.post()
    hub_of(request).db.delete_measurement(int(request.match_info["id"]))
    raise redirect(
        safe_next(form.get("next")),
        "Weigh deleted. Anything already sent to Google stays there.",
    )


# -- onboarding -----------------------------------------------------------------


def steps(current: int) -> str:
    bars = "".join(
        f'<span class="{"is-done" if i <= current else ""}"></span>' for i in (1, 2, 3)
    )
    return f"""<div class="onboard-head"><span class="brand">{brand_mark()}Bathroom Hub</span><span class="muted-small">Step {current} of 3</span></div>
<div class="progress" aria-hidden="true">{bars}</div>"""


def brand_mark() -> str:
    return (
        '<svg width="26" height="26" viewBox="0 0 26 26" aria-hidden="true" class="brand-mark"><circle cx="13" cy="13" r="12"/>'
        '<path d="M8 15.5c1.6-3.6 8.4-3.6 10 0"/></svg>'
    )


async def welcome(request: web.Request) -> web.Response:
    hub = hub_of(request)
    if hub.db.profiles():
        raise web.HTTPFound("/")
    values: dict[str, Any] = {}
    errors: list[str] = []
    if request.method == "POST":
        values, errors = parse_profile(await request.post())
        if not errors:
            profile_id = hub.db.create_profile(values)
            response = web.HTTPFound("/welcome/google")
            response.set_cookie(
                PROFILE_COOKIE,
                str(profile_id),
                max_age=365 * 86400,
                samesite="Lax",
                httponly=True,
            )
            raise response
    body = f"""{steps(1)}
<h1 class="onboard-title">Let's set up your first profile</h1>
<p class="lede">Your details let the hub recognise your weighs and estimate body fat. They stay on this hub.</p>
{profile_fields(values, errors, "/welcome", "Continue", cancel=None)}
<p class="center muted-small">Next: connect Google Health, then pair your scale</p>"""
    return page("Welcome", body, width="narrow")


async def welcome_google(request: web.Request) -> web.Response:
    hub = hub_of(request)
    profiles = hub.db.profiles()
    if not profiles:
        raise web.HTTPFound("/welcome")
    profile = current_profile(request, profiles)
    if hub.db.google_link(profile["id"]):
        action = f'<div class="card ok-card">{icon("check")}<p><strong>Google Health is connected for {e(profile["name"])}.</strong></p></div>'
        primary = (
            '<a class="btn btn-primary btn-block" href="/welcome/scale">Continue</a>'
        )
    elif hub.google_client():
        action = ""
        primary = f'<a class="btn btn-primary btn-block" href="/profiles/{profile["id"]}/google?next=/welcome/scale">Connect Google Health</a>'
    else:
        action = """<div class="card"><p><strong>One-time setup first.</strong> The hub needs its own Google Cloud OAuth client.
It takes about 10 minutes and the steps are in Settings.</p></div>"""
        primary = '<a class="btn btn-primary btn-block" href="/settings?next=/welcome/google&amp;back=/welcome/google">Set up Google</a>'
    body = f"""{steps(2)}
<h1 class="onboard-title">Send weighs to Google Health</h1>
<p class="lede">Each person's weight and body fat go to their own Google account, so they show up in the apps they already use.</p>
{action}
<div class="stack-bottom">{primary}<a class="btn btn-ghost btn-block" href="/welcome/scale">Skip for now</a></div>"""
    return page("Connect Google Health", body, width="narrow")


async def welcome_scale(request: web.Request) -> web.Response:
    status = status_of(request)
    if status["paired"]:
        content = f"""<div class="card ok-card">{icon("check")}<p><strong>Your scale is paired.</strong> Step on it barefoot and the weigh appears on your dashboard.</p></div>
<div class="stack-bottom"><a class="btn btn-primary btn-block" href="/">Go to dashboard</a></div>"""
    else:
        content = f"""{pairing_panel(status, "/welcome/scale")}
<div class="stack-bottom"><a class="btn btn-ghost btn-block" href="/">Skip for now</a></div>"""
    body = f"""{steps(3)}
<h1 class="onboard-title">Pair your scale</h1>
<p class="lede">The hub listens for the Philips DL8780 around the clock. Pair it once and every weigh comes in by itself.</p>
{content}"""
    return page("Pair your scale", body, width="narrow", poll=True)


def pairing_panel(status: dict[str, Any], next_url: str) -> str:
    """Steps plus the live pairing state, shared by onboarding and Add device."""
    result = ""
    if status.get("last_pair_result") == "failed":
        result = f'<p class="error-text">{icon("alert", 16)} Pairing did not complete. Try again.</p>'
    if status["pairing"]:
        return f"""<section class="card pairing" aria-live="polite">
<div class="card-head"><h2>Waiting for the scale</h2><span class="badge warn"><span data-countdown="{status["pairing_seconds_left"]}">{status["pairing_seconds_left"]}</span> s</span></div>
<ol class="numbered"><li class="is-done">Pairing window open</li><li class="is-now">Hold the <strong>unit button</strong> on the scale for 3 seconds, until the pairing symbols alternate</li><li>The scale shows a check mark when it is paired</li></ol>
{result}</section>"""
    disabled = status.get("state") == "disabled"
    return f"""<section class="card pairing">
<ol class="numbered"><li>Press <strong>Start pairing</strong> below</li><li>Hold the <strong>unit button</strong> on the scale for 3 seconds, until the pairing symbols alternate</li><li>Wait for the check mark on the scale</li></ol>
{result}
{f'<p class="error-text">{icon("alert", 16)} Bluetooth is off on the hub, so it cannot pair.</p>' if disabled else ""}
<form method="post" action="/devices/pair"><input type="hidden" name="next" value="{e(next_url)}">
<button class="btn btn-primary btn-block"{" disabled" if disabled else ""}>Start pairing</button></form>
</section>"""


# -- devices -----------------------------------------------------------------------


def device_row(device: dict[str, Any]) -> str:
    detail = device["model"]
    if device["last_weigh"]:
        detail += " · " + when(device["last_weigh"].isoformat())
    dot = f'<span class="dot {"ok" if device["state"] == "online" else "warn"}" role="img" aria-label="{e(device["note"])}"></span>'
    return f"""<li><a href="/devices/{e(device["id"])}" class="row-item row-link">
<span class="icon-tile">{icon(CATEGORY_ICON.get(device["category"], "devices"), 18)}</span>
<div class="row-text"><strong>{e(device["name"])}</strong><small>{e(detail)}</small></div>{dot}</a></li>"""


async def devices_page(request: web.Request) -> web.Response:
    hub = hub_of(request)
    status = status_of(request)
    all_devices = devices.hub_devices(status, hub.db)
    query = request.query.get("q", "").strip()
    show = request.query.get("show", "all")
    group = request.query.get("group", "room")
    listed = [
        d
        for d in all_devices
        if not query or query.lower() in f'{d["name"]} {d["model"]} {d["room"]}'.lower()
    ]
    if show == "attention":
        listed = [d for d in listed if d["state"] != "online"]
    attention = [d for d in listed if d["state"] != "online"]
    online = sum(1 for d in all_devices if d["state"] == "online")

    listening = status["state"] != "disabled"
    hub_card = f"""<section class="card hub-card" aria-label="This hub"><span class="icon-tile on-accent">{icon("hub", 22)}</span>
<div class="row-text"><strong>{"This hub is listening" if listening else "Bluetooth is off"}</strong>
<small>{e("Last contact with a device " + ago(status["last_seen"]) if status["last_seen"] else "Raspberry Pi · waiting for devices")}</small></div></section>"""

    tools = ""
    if len(all_devices) > 5:
        chips = "".join(
            f'<a class="chip{" is-on" if key == show else ""}" href="{e(with_query("/devices", q=query, show=key, group=group))}">{e(label)}</a>'
            for key, label in (
                ("all", f"All {len(all_devices)}"),
                ("attention", f"Needs attention {len(all_devices) - online}"),
            )
        )
        tools = f"""<form class="search" role="search" method="get" action="/devices"><label class="sr-only" for="q">Search your devices</label>
{icon("search", 18)}<input id="q" name="q" value="{e(query)}" placeholder="Search by name, model or room"><input type="hidden" name="group" value="{e(group)}"></form>
<nav class="chips" aria-label="Filter">{chips}</nav>"""

    sections = []
    if attention:
        sections.append(f"""<section class="card notice list-card" aria-labelledby="att"><h2 id="att" class="eyebrow warn-text">Needs attention</h2>
<ul class="rows">{"".join(device_row(d) for d in attention)}</ul></section>""")
    key = "category" if group == "type" else "room"
    groups: dict[str, list[dict[str, Any]]] = {}
    for device in listed:
        if device in attention:
            continue
        groups.setdefault(device[key], []).append(device)
    for name, members in sorted(groups.items()):
        head, rest = members[:4], members[4:]
        more = (
            f'<li><details class="more"><summary>Show {len(rest)} more</summary><ul class="rows">{"".join(device_row(d) for d in rest)}</ul></details></li>'
            if rest
            else ""
        )
        sections.append(f"""<section aria-label="{e(name)}"><h2 class="group-head"><span>{e(name)}</span><span>{len(members)}</span></h2>
<ul class="rows card list-card">{"".join(device_row(d) for d in head)}{more}</ul></section>""")
    if not all_devices:
        sections.append(
            """<section class="card empty"><p><strong>No devices yet.</strong></p><p>Add your scale to start receiving weighs.</p></section>"""
        )
    elif not listed:
        sections.append(
            '<section class="card empty"><p>No devices match.</p></section>'
        )

    group_toggle = ""
    if len(all_devices) > 1:
        other = "type" if group == "room" else "room"
        group_toggle = f'<p class="group-toggle">Grouped by {e(group)} · <a href="{e(with_query("/devices", q=query, show=show, group=other))}">group by {other}</a></p>'
    summary = (
        f'{len(all_devices)} device{"s" if len(all_devices) != 1 else ""} · {online} online'
        if all_devices
        else "Nothing paired yet"
    )
    body = f"""{topbar("Device hub", back="/", sub=e(summary))}
{hub_card}{tools}{group_toggle}
<div class="stack">{"".join(sections)}</div>
<div class="sticky-cta"><a href="/devices/add" class="btn btn-primary btn-block">{icon("plus", 18)}Add device</a></div>"""
    return page("Device hub", body, flash=request.query.get("flash"), poll=True)


async def add_device(request: web.Request) -> web.Response:
    status = status_of(request)
    query = request.query.get("q", "").strip()
    category = request.query.get("category", "")
    paired_address = status.get("address") if status.get("paired") else None

    nearby_rows = []
    for item in status.get("nearby", []):
        model = devices.model_info(item.get("model", ""))
        title = (
            f'Philips {model.name.lower()} {item.get("model")}'
            if model
            else (item.get("name") or "Unknown device")
        )
        if (
            paired_address
            and item["address"] == paired_address
            and not item["pairing_mode"]
        ):
            state, action = "Already paired", ""
        elif item["pairing_mode"]:
            state = "Ready to pair"
            action = (
                ""
                if status["pairing"]
                else '<form method="post" action="/devices/pair"><input type="hidden" name="next" value="/devices/add">'
                '<button class="btn btn-primary btn-sm">Pair</button></form>'
            )
        else:
            state, action = "Not in pairing mode", ""
        signal = f' · {item["rssi"]} dBm' if item.get("rssi") is not None else ""
        nearby_rows.append(f"""<li class="row-item found{" is-ready" if item["pairing_mode"] else ""}"><span class="icon-tile">{icon("scale", 18)}</span>
<div class="row-text"><strong>{e(title)}</strong><small>{e(state + signal)}</small></div>{action}</li>""")
    if status["state"] == "disabled":
        scanning = f'<span class="muted-small">{icon("alert", 16)} Bluetooth off</span>'
    else:
        scanning = '<span class="muted-small spinner-label"><span class="spinner" aria-hidden="true"></span>Searching</span>'
    nearby = f"""<section class="card" aria-labelledby="near"><div class="card-head"><h2 id="near">Found nearby</h2>{scanning}</div>
<p class="muted-small">Devices in pairing mode show up here first.</p>
{f'<ul class="rows">{"".join(nearby_rows)}</ul>' if nearby_rows else '<p class="empty-inline">Nothing nearby yet. Put the device in pairing mode.</p>'}
</section>"""
    pairing = (
        pairing_panel(status, "/devices/add")
        if status["pairing"] or status.get("last_pair_result") == "failed"
        else ""
    )
    if status.get("last_pair_result") == "paired" and not status["pairing"]:
        pairing = f'<div class="card ok-card">{icon("check")}<p><strong>Scale paired.</strong> Step on it barefoot to send a weigh.</p></div>'

    if query or category:
        results = devices.search_catalogue(query, category)
        items = []
        for model in results:
            if model.support == "supported":
                support = badge("Supported", "ok")
                extra = (
                    (
                        f'<p class="muted-small">{e(model.pairing)}</p>'
                        '<form method="post" action="/devices/pair"><input type="hidden" name="next" value="/devices/add">'
                        '<button class="btn btn-secondary btn-sm">Start pairing</button></form>'
                    )
                    if model.pairing
                    else ""
                )
            else:
                support, extra = (
                    badge("Planned"),
                    '<p class="muted-small">Not supported yet.</p>',
                )
            items.append(f"""<li class="catalogue-item"><div class="row-item"><span class="icon-tile">{icon(CATEGORY_ICON.get(model.category, "devices"), 18)}</span>
<div class="row-text"><strong>{e(model.name)}</strong><small>{e(model.model)} · {e(model.measures)}</small></div>{support}</div>{extra}</li>""")
        heading = e(category or f'Results for "{query}"')
        browse = f"""<div class="card-head"><h3>{heading}</h3><a class="link-small" href="/devices/add">All types</a></div>
{f'<ul class="rows">{"".join(items)}</ul>' if items else '<p class="empty-inline">No supported device matches.</p>'}"""
    else:
        tiles = "".join(
            f'<a class="type-tile" href="/devices/add?category={quote(name)}">{icon(CATEGORY_ICON.get(name, "devices"), 24)}'
            f'<span><strong>{e(name)}</strong><small>{count} model{"s" if count != 1 else ""}</small></span></a>'
            for name, count in devices.category_counts()
        )
        browse = f'<div class="type-grid">{tiles}</div>'
    catalogue = f"""<section aria-labelledby="find"><h2 id="find" class="section-title">Or find your device</h2>
<form class="search" role="search" method="get" action="/devices/add"><label class="sr-only" for="cq">Search supported devices</label>
{icon("search", 18)}<input id="cq" name="q" value="{e(query)}" placeholder="Model number, e.g. DL8780"></form>
{browse}</section>
<p class="muted-small footnote">Don't see your device? It may not be supported yet.</p>"""
    body = f"""{topbar("Add device", back="/devices")}{pairing}{nearby}{catalogue}"""
    return page("Add device", body, flash=request.query.get("flash"), poll=True)


async def device_detail(request: web.Request) -> web.Response:
    hub = hub_of(request)
    status = status_of(request)
    device = next(
        (
            d
            for d in devices.hub_devices(status, hub.db)
            if d["id"] == request.match_info["id"]
        ),
        None,
    )
    if device is None:
        raise web.HTTPNotFound()
    model = devices.model_info(device["model"])
    tone = "ok" if device["state"] == "online" else "warn"
    facts = [
        ("Status", device["note"]),
        (
            "Last weigh",
            when(device["last_weigh"].isoformat())
            if device["last_weigh"]
            else "None yet",
        ),
        ("Last contact", ago(status["last_seen"])),
        ("Measures", model.measures if model else "—"),
        ("Model", f'Philips {device["model"]}'),
        ("Serial", device["serial"] or "—"),
        ("Address", device["address"] or "—"),
    ]
    facts_html = "".join(f'<div><dt>{e(k)}</dt><dd>{e(v)}</dd></div>' for k, v in facts)
    body = f"""{topbar(device["name"], back="/devices", sub=e(device["room"]))}
<section class="card device-hero"><span class="icon-tile big {tone}">{icon(CATEGORY_ICON.get(device["category"], "devices"), 28)}</span>
<div class="row-text"><strong>{e(device["note"])}</strong><small>Philips {e(device["model"])}</small></div>{badge("Paired" if status["paired"] else "Not paired", tone)}</section>
<section class="card" aria-labelledby="info"><h2 id="info" class="eyebrow">Details</h2><dl class="facts">{facts_html}</dl></section>
<section class="card" aria-labelledby="name-h"><h2 id="name-h" class="eyebrow">Name and room</h2>
<form method="post" action="/devices/{e(device["id"])}" class="form">
<div class="field-row"><label class="field">Name<input name="name" maxlength="40" required value="{e(device["name"])}"></label>
<label class="field">Room<input name="room" maxlength="40" required value="{e(device["room"])}" list="rooms"></label></div>
<datalist id="rooms"><option value="Bathroom"><option value="Bedroom"><option value="Hallway"></datalist>
<button class="btn btn-secondary">Save</button></form></section>
<section class="card" aria-labelledby="pair-h"><h2 id="pair-h" class="eyebrow">Pairing</h2>
<p class="muted-small">Pair again when the scale was paired to another app, or stopped sending weighs.</p>
<div class="actions"><form method="post" action="/devices/pair"><input type="hidden" name="next" value="/devices/add"><button class="btn btn-secondary">Pair again</button></form>
<form method="post" action="/devices/{e(device["id"])}/forget" data-confirm="Forget this scale? The hub stops receiving its weighs until you pair it again.">
<button class="btn-link danger">Forget device</button></form></div></section>"""
    return page(device["name"], body, flash=request.query.get("flash"), poll=True)


async def save_device(request: web.Request) -> web.Response:
    if request.match_info["id"] != devices.SCALE_ID:
        raise web.HTTPNotFound()
    hub = hub_of(request)
    form = await request.post()
    name = str(form.get("name", "")).strip()[:40]
    room = str(form.get("room", "")).strip()[:40]
    if name:
        hub.db.set_setting("device_scale_name", name)
    if room:
        hub.db.set_setting("device_scale_room", room)
    raise redirect(f"/devices/{devices.SCALE_ID}", "Saved.")


async def forget_device(request: web.Request) -> web.Response:
    if request.match_info["id"] != devices.SCALE_ID:
        raise web.HTTPNotFound()
    request.app[LISTENER_KEY].forget()
    raise redirect("/devices", "Scale forgotten.")


async def pair_device(request: web.Request) -> web.Response:
    form = await request.post()
    request.app[LISTENER_KEY].start_pairing()
    raise redirect(safe_next(form.get("next"), "/devices/add"))


async def api_status(request: web.Request) -> web.Response:
    hub = hub_of(request)
    status = dict(status_of(request))
    last_event = hub.db.conn.execute("SELECT MAX(id) AS id FROM events").fetchone()[
        "id"
    ]
    last_weigh = hub.db.conn.execute(
        "SELECT MAX(id) AS id FROM measurements"
    ).fetchone()["id"]
    nearby = ",".join(
        f'{n["address"]}:{int(n["pairing_mode"])}' for n in status.get("nearby", [])
    )
    status["version"] = (
        f'{last_event}-{last_weigh}-{status["paired"]}-{status["pairing"]}-{status["state"]}-{nearby}'
    )
    return web.json_response(status)


# -- people ----------------------------------------------------------------------


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


def profile_fields(
    values: dict[str, Any],
    errors: list[str],
    action: str,
    submit: str,
    cancel: str | None = "/profiles",
    weight_label: str = "Weight today",
) -> str:
    error_html = "".join(f"<li>{e(err)}</li>" for err in errors)
    sex = values.get("sex")
    height = values.get("height_cm")
    weight = values.get("start_weight_kg")
    cancel_html = (
        f'<a href="{e(cancel)}" class="btn btn-ghost btn-block">Cancel</a>'
        if cancel
        else ""
    )
    return f"""<form method="post" action="{e(action)}" class="form">
{f'<ul class="errors" role="alert">{error_html}</ul>' if errors else ""}
<label class="field">Name<input name="name" required maxlength="40" autocomplete="given-name" value="{e(values.get("name"))}"></label>
<fieldset class="field"><legend>Sex <span class="muted-inline">· used by the body-fat formula</span></legend>
<div class="seg seg-input">
<label><input type="radio" name="sex" value="male" required{" checked" if sex == "male" else ""}><span>Male</span></label>
<label><input type="radio" name="sex" value="female"{" checked" if sex == "female" else ""}><span>Female</span></label>
</div></fieldset>
<label class="field">Date of birth<input type="date" name="birth_date" required value="{e(values.get("birth_date"))}"></label>
<div class="field-row">
<label class="field">Height<span class="with-unit"><input name="height_cm" inputmode="decimal" required value="{e(f"{height:g}" if isinstance(height, float) else height)}"><span>cm</span></span></label>
<label class="field">{e(weight_label)}<span class="with-unit"><input name="start_weight_kg" inputmode="decimal" value="{e(f"{weight:g}" if isinstance(weight, float) else weight)}"><span>kg</span></span></label>
</div>
<p class="hint">An estimate is fine. It's only used to recognise the first weighs.</p>
<div class="stack-bottom"><button class="btn btn-primary btn-block">{e(submit)}</button>{cancel_html}</div>
</form>"""


async def profiles_page(request: web.Request) -> web.Response:
    hub = hub_of(request)
    profiles = hub.db.profiles()
    if not profiles:
        raise web.HTTPFound("/welcome")
    refs = hub.references()
    cards = []
    for p in profiles:
        ref = refs.get(p["id"])
        if p["google_linked"]:
            google = (
                badge("Google error", "error")
                if p["google_last_error"]
                else badge("Google connected", "ok")
            )
        else:
            google = badge("No Google account")
        cards.append(f"""<li><a href="/profiles/{p["id"]}/edit" class="row-item row-link person">{avatar(p)}
<div class="row-text"><strong>{e(p["name"])}</strong><small>{e(profile_meta(p))} · recognised around {f"{ref:.1f} kg" if ref else "—"}</small></div>{google}</a></li>""")
    body = f"""{topbar("People", back="/", sub="Everyone who uses the scale")}
<ul class="rows card list-card">{"".join(cards)}</ul>
<div class="sticky-cta"><a href="/profiles/new" class="btn btn-primary btn-block">{icon("plus", 18)}Add person</a></div>"""
    return page("People", body, flash=request.query.get("flash"))


async def new_profile(request: web.Request) -> web.Response:
    hub = hub_of(request)
    values: dict[str, Any] = {}
    errors: list[str] = []
    if request.method == "POST":
        values, errors = parse_profile(await request.post())
        if not errors:
            hub.db.create_profile(values)
            raise redirect("/profiles", f"Added {values['name']}.")
    body = f"""{topbar("Add person", back="/profiles")}<section class="card">{profile_fields(values, errors, "/profiles/new", "Add person")}</section>"""
    return page("Add person", body)


async def edit_profile(request: web.Request) -> web.Response:
    hub = hub_of(request)
    profile_id = int(request.match_info["id"])
    profile = hub.db.profile(profile_id)
    if profile is None:
        raise web.HTTPNotFound()
    errors: list[str] = []
    values: dict[str, Any] = dict(profile)
    if request.method == "POST":
        values, errors = parse_profile(await request.post())
        if not errors:
            hub.db.update_profile(profile_id, values)
            hub.recompute_profile(profile_id)
            raise redirect("/profiles", f"Saved {values['name']}.")
    link = hub.db.google_link(profile_id)
    if link is None:
        google = f"""<p class="muted-small">Not connected. Weighs stay on the hub.</p>
<a class="btn btn-secondary" href="/profiles/{profile_id}/google?next=/profiles/{profile_id}/edit">Connect Google Health</a>"""
    else:
        state = (
            f'<p class="error-text">{icon("alert", 16)} {e(link["last_error"])}</p>'
            if link["last_error"]
            else f'<p class="ok-text">{icon("check", 16)} Connected{" · last sent " + e(when(link["last_ok_at"])) if link["last_ok_at"] else ""}</p>'
        )
        google = f"""{state}<div class="actions"><a class="btn btn-secondary" href="/profiles/{profile_id}/google?new=1&amp;next=/profiles/{profile_id}/edit">Reconnect</a>
<form method="post" action="/profiles/{profile_id}/google/unlink" data-confirm="Disconnect this Google account? Remove the hub's access in the Google account too.">
<button class="btn-link danger">Disconnect</button></form></div>"""
    body = f"""{topbar(profile["name"], back="/profiles")}
<section class="card">{profile_fields(values, errors, f"/profiles/{profile_id}/edit", "Save", cancel=None, weight_label="Starting weight")}</section>
<section class="card" aria-labelledby="g"><h2 id="g" class="eyebrow">Google Health</h2>{google}</section>
<form method="post" action="/profiles/{profile_id}/delete" class="danger-zone" data-confirm="Delete {e(profile["name"])}? Their weighs stay on the hub without a person.">
<button class="btn-link danger">Delete this person</button></form>"""
    return page(profile["name"], body, flash=request.query.get("flash"))


async def delete_profile(request: web.Request) -> web.Response:
    hub_of(request).db.delete_profile(int(request.match_info["id"]))
    raise redirect("/profiles", "Person deleted.")


# -- google linking --------------------------------------------------------------


async def google_link_page(request: web.Request) -> web.Response:
    hub = hub_of(request)
    profile_id = int(request.match_info["id"])
    profile = hub.db.profile(profile_id)
    if profile is None:
        raise web.HTTPNotFound()
    next_url = safe_next(request.query.get("next"), "/profiles")
    client = hub.google_client()
    if client is None:
        raise redirect(
            with_query(
                "/settings",
                next=with_query(f"/profiles/{profile_id}/google", next=next_url),
                back=next_url,
            ),
            "Add the hub's Google OAuth client first.",
        )
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
    body = f"""{topbar("Connect Google Health", back=next_url, sub=e(f"for {profile['name']}"))}
{f'<div class="card error-card" role="alert">{icon("alert")}<p>{e(error)}</p></div>' if error else ""}
<section class="card">
<ol class="numbered big-steps">
<li><strong>Sign in with {e(profile["name"])}'s Google account</strong> and allow access to health measurements.
<a class="btn btn-primary btn-block" href="{e(url)}" target="_blank" rel="noopener">Sign in with Google</a></li>
<li><strong>Google then opens a page that doesn't load.</strong> That's expected: its address starts with <code>http://localhost/?state=</code>.</li>
<li><strong>Copy that whole address</strong> from the address bar and paste it below. On a phone, tap the address bar, then Select all and Copy.</li>
</ol>
<form method="post" action="/profiles/{profile_id}/google" class="form">
<input type="hidden" name="next" value="{e(next_url)}">
<label class="field">Address after signing in<input name="redirect" required placeholder="http://localhost/?state=…&amp;code=…" autocomplete="off" autocapitalize="off" spellcheck="false"></label>
<div class="stack-bottom"><button class="btn btn-primary btn-block">Connect</button>
<a class="btn btn-ghost btn-block" href="{e(next_url)}">Cancel</a></div>
</form></section>"""
    return page("Connect Google Health", body, width="narrow")


async def google_link_finish(request: web.Request) -> web.Response:
    hub = hub_of(request)
    profile_id = int(request.match_info["id"])
    form = await request.post()
    next_url = safe_next(form.get("next"), "/profiles")
    client = hub.google_client()
    try:
        if client is None:
            raise google_health.GoogleError(
                "Add the hub's Google OAuth client in Settings first."
            )
        code, state = google_health.parse_redirect(str(form.get("redirect", "")))
        pending = (
            hub.db.take_oauth_pending(state)
            if state
            else hub.db.oauth_pending_for(profile_id)
        )
        if pending is None or pending["profile_id"] != profile_id:
            raise google_health.GoogleError(
                "That sign-in belongs to a different or expired request. Start again."
            )
        if state is None:
            hub.db.take_oauth_pending(pending["state"])
        tokens = await google_health.exchange_code(
            await hub.http(),
            client_id=client[0],
            client_secret=client[1],
            code=code,
            verifier=pending["verifier"],
        )
    except google_health.GoogleError as exc:
        raise web.HTTPFound(
            with_query(
                f"/profiles/{profile_id}/google", new=1, error=str(exc), next=next_url
            )
        )
    hub.db.save_google_link(
        profile_id,
        tokens["refresh_token"],
        tokens.get("access_token"),
        tokens.get("expires_at"),
    )
    hub.db.log(f"Linked a Google account to {hub.db.profile(profile_id)['name']}")
    for row in hub.db.conn.execute(
        "SELECT id FROM measurements WHERE profile_id = ? AND google_status = 'none'",
        (profile_id,),
    ).fetchall():
        hub.db.update_measurement(row["id"], {"google_status": "pending"})
    hub.kick_uploads()
    raise redirect(next_url, "Google Health connected. Earlier weighs are being sent.")


async def google_unlink(request: web.Request) -> web.Response:
    hub = hub_of(request)
    profile_id = int(request.match_info["id"])
    hub.db.delete_google_link(profile_id)
    raise redirect(
        f"/profiles/{profile_id}/edit",
        "Disconnected. Remove the hub's access in that Google account as well.",
    )


# -- settings -------------------------------------------------------------------------


async def settings_page(request: web.Request) -> web.Response:
    hub = hub_of(request)
    next_url = safe_next(request.query.get("next"), "")
    # "next" is where saving continues to; "back" is where the back arrow goes. They differ when Settings
    # interrupts a flow (connecting Google) whose page would only send the person straight back here.
    back_url = safe_next(request.query.get("back"), "/")
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
        target = safe_next(form.get("next"), "")
        raise redirect(target or "/settings", "Settings saved.")
    has_secret = bool(hub.db.get_setting("google_client_secret"))
    events = "".join(
        f'<li class="event {e(ev["level"])}"><time>{e(when(ev["at"]))}</time><span>{e(ev["message"])}</span></li>'
        for ev in hub.db.events(20)
    )
    body = f"""{topbar("Settings", back=back_url)}
<form method="post" action="/settings" class="stack">
<input type="hidden" name="next" value="{e(next_url)}">
<section class="card" aria-labelledby="gh"><h2 id="gh" class="eyebrow">Google Health</h2>
<p>Each person's weighs go to their own Google account. The hub needs one OAuth client, created once:</p>
<ol class="numbered">
<li>In the <a href="https://console.cloud.google.com/" target="_blank" rel="noopener">Google Cloud console</a>, create a project and enable the <strong>Google Health API</strong>.</li>
<li>Set up the OAuth consent screen (External) and add the scope <code>{e(google_health.SCOPE.rsplit("/", 1)[1])}</code>. While the app is in <em>Testing</em>, add every person as a test user. Google ends test-mode sign-ins after 7 days, so publish the app for continuous syncing.</li>
<li>Create an OAuth client ID of type <strong>Desktop app</strong> and paste its ID and secret here.</li>
</ol>
<label class="field">Client ID<input name="google_client_id" value="{e(hub.db.get_setting("google_client_id"))}" autocomplete="off" spellcheck="false"></label>
<label class="field">Client secret<input name="google_client_secret" type="password" placeholder="{"Saved. Leave empty to keep it" if has_secret else ""}" autocomplete="off"></label>
</section>
<section class="card" aria-labelledby="rp"><h2 id="rp" class="eyebrow">Recognising people</h2>
<label class="field">Match weighs within<span class="with-unit"><input name="assign_tolerance_kg" inputmode="decimal" value="{e(f"{hub.tolerance():g}")}"><span>kg</span></span></label>
<p class="hint">A weigh goes to the person whose recent weight is closest, if it's within this range and clearly closer than anyone else. Otherwise the dashboard asks who it was.</p>
</section>
<div class="sticky-cta"><button class="btn btn-primary btn-block">{"Save and continue" if next_url else "Save settings"}</button></div>
</form>
<section class="card" aria-labelledby="bc"><h2 id="bc" class="eyebrow">Body composition</h2>
<p>Body fat is calculated per person from the scale's impedance with the Jebb et al. (2000) equation for foot-to-foot scales. Typical individual error is about ±4.8 % for men and ±3.3 % for women. Lean mass is weight minus fat. The scale's own body-fat figure is stored but not used.</p></section>
<section class="card" aria-labelledby="act"><h2 id="act" class="eyebrow">Recent activity</h2>
<ul class="events">{events or '<li class="muted-small">Nothing yet.</li>'}</ul></section>"""
    return page("Settings", body, flash=request.query.get("flash"))


def create_app(hub: Hub, listener: Any) -> web.Application:
    app = web.Application()
    app[HUB_KEY] = hub
    app[LISTENER_KEY] = listener
    app.router.add_get("/", dashboard)
    app.router.add_route("*", "/welcome", welcome)
    app.router.add_get("/welcome/google", welcome_google)
    app.router.add_get("/welcome/scale", welcome_scale)
    app.router.add_get("/history", history)
    app.router.add_get("/api/status", api_status)
    app.router.add_get("/devices", devices_page)
    app.router.add_get("/devices/add", add_device)
    app.router.add_post("/devices/pair", pair_device)
    app.router.add_get("/devices/{id}", device_detail)
    app.router.add_post("/devices/{id}", save_device)
    app.router.add_post("/devices/{id}/forget", forget_device)
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
