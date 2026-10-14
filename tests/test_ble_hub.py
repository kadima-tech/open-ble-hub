"""Open BLE Hub: body composition, assignment, ingest, Google payloads and the UI."""

from __future__ import annotations

import asyncio
import unittest
from datetime import UTC, date, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from aiohttp.test_utils import TestClient, TestServer

from ble_hub import assign, bodycomp, charts, devices, google_health
from ble_hub.__main__ import NoBluetooth
from ble_hub.db import Database
from ble_hub.hub import Hub, scale_time
from ble_hub.web import create_app
from philips_ble.scale_packets import parse_a3_append, parse_a3_weight

# Captured from the DL8780 on 2026-10-13 (PHS Health HCI capture).
WEIGHT_RAW = bytes.fromhex(
    "1f 16 26 00 fe 89 50 91 1f 00 00 00 00 17 13 00 ff 01 19 00"
)
APPEND_RAW = bytes.fromhex(
    "6d 89 50 91 1f 01 fc f0 32 f2 79 f1 26 f0 00 00 00 00 00 00"
)
ME = {
    "name": "Me",
    "sex": "male",
    "birth_date": "1990-01-01",
    "height_cm": 183.0,
    "start_weight_kg": 97.0,
}
GUEST = {
    "name": "Guest",
    "sex": "female",
    "birth_date": "1996-01-01",
    "height_cm": 170.0,
    "start_weight_kg": 105.0,
}


class PairedListener:
    """Listener stand-in that reports a paired scale and one nearby in pairing mode."""

    def __init__(self):
        self.pairing = False
        self.forgotten = False

    def status(self):
        return {
            "state": "scanning",
            "address": "AA:BB",
            "paired": not self.forgotten,
            "pairing": self.pairing,
            "pairing_seconds_left": 180 if self.pairing else 0,
            "last_pair_result": None,
            "last_seen": None,
            "last_error": None,
            "nearby": [
                {
                    "address": "CC:DD",
                    "name": "1DL87801",
                    "model": "DL8780",
                    "rssi": -50,
                    "seen": 0,
                    "pairing_mode": True,
                }
            ],
        }

    def start_pairing(self, seconds=180):
        self.pairing = True

    def forget(self):
        self.forgotten = True


class ChartAndCatalogueTests(unittest.TestCase):
    def test_line_chart_needs_two_points(self):
        start, end = (
            datetime(2026, 9, 14, tzinfo=UTC),
            datetime(2026, 10, 14, tzinfo=UTC),
        )
        self.assertEqual(
            charts.line_chart(
                [(end, 97.5)], start=start, end=end, tone="weight", label="x"
            ),
            "",
        )
        svg = charts.line_chart(
            [(start, 99.0), (end, 97.5)], start=start, end=end, tone="weight", label="x"
        )
        self.assertIn("<polyline", svg)
        self.assertIn("99.0", svg)

    def test_catalogue_search(self):
        self.assertEqual(
            [m.model for m in devices.search_catalogue("dl87")], ["DL8780"]
        )
        self.assertEqual(
            [m.model for m in devices.search_catalogue(category="Oral care")],
            ["HX9393"],
        )
        self.assertEqual(devices.search_catalogue("nothing-like-this"), [])


class BodyCompositionTests(unittest.TestCase):
    def test_jebb_matches_the_comparison_run(self):
        # Same inputs as scratchpad/tools/bia_compare.py, which gave 27.5 % and 46.9 %.
        self.assertAlmostEqual(
            bodycomp.jebb2000_fat_pct(
                male=True, age=36, height_cm=183, weight_kg=97.5, impedance=491.1
            ),
            27.5,
            places=1,
        )
        self.assertAlmostEqual(
            bodycomp.jebb2000_fat_pct(
                male=False, age=30, height_cm=170, weight_kg=105.0, impedance=486.3
            ),
            46.9,
            places=1,
        )

    def test_composition_derives_lean_mass_and_bmi(self):
        comp = bodycomp.composition(
            male=True,
            birth=date(1990, 1, 1),
            height_cm=183,
            weight_kg=97.5,
            impedance=491.1,
            when=date(2026, 10, 13),
        )
        self.assertEqual(comp.fat_pct, 27.5)
        self.assertAlmostEqual(comp.lean_kg, 97.5 - comp.fat_kg, places=1)
        self.assertEqual(comp.bmi, 29.1)

    def test_no_impedance_means_no_composition(self):
        self.assertIsNone(
            bodycomp.composition(
                male=True,
                birth=date(1990, 1, 1),
                height_cm=183,
                weight_kg=97.5,
                impedance=None,
                when=date(2026, 1, 1),
            )
        )

    def test_age_counts_birthdays(self):
        self.assertEqual(bodycomp.age_on(date(1990, 10, 14), date(2026, 10, 13)), 35)
        self.assertEqual(bodycomp.age_on(date(1990, 10, 13), date(2026, 10, 13)), 36)


class AssignmentTests(unittest.TestCase):
    def test_reference_is_median_of_recent_weighs(self):
        self.assertEqual(assign.reference_weight([97.0, 97.4, 120.0], 90.0), 97.4)
        self.assertEqual(assign.reference_weight([], 90.0), 90.0)

    def test_clear_winner_is_assigned(self):
        self.assertEqual(assign.choose_profile(97.3, {1: 97.5, 2: 105.0}).profile_id, 1)
        self.assertEqual(
            assign.choose_profile(104.8, {1: 97.5, 2: 105.0}).profile_id, 2
        )

    def test_close_profiles_need_a_manual_choice(self):
        self.assertIsNone(assign.choose_profile(80.0, {1: 79.5, 2: 80.6}).profile_id)

    def test_far_from_everyone_needs_a_manual_choice(self):
        self.assertIsNone(assign.choose_profile(60.0, {1: 97.5, 2: 105.0}).profile_id)
        self.assertIsNone(assign.choose_profile(60.0, {}).profile_id)


class GooglePayloadTests(unittest.TestCase):
    def test_weight_and_body_fat_points(self):
        when = datetime(2026, 10, 13, 17, 50, 13, tzinfo=UTC)
        weight = google_health.weight_point(97.5, when, 7200)
        self.assertEqual(weight["weight"]["weightGrams"], 97500)
        self.assertEqual(
            weight["weight"]["sampleTime"],
            {"physicalTime": "2026-10-13T17:50:13Z", "utcOffset": "7200s"},
        )
        fat = google_health.body_fat_point(27.46, when, 7200)
        self.assertEqual(fat["bodyFat"]["percentage"], 27.5)

    def test_parse_redirect(self):
        code, state = google_health.parse_redirect(
            "http://localhost/?state=abc&code=4%2F0Ad&scope=x"
        )
        self.assertEqual((code, state), ("4/0Ad", "abc"))
        self.assertEqual(google_health.parse_redirect("  rawcode "), ("rawcode", None))
        with self.assertRaises(google_health.GoogleError):
            google_health.parse_redirect("http://localhost/?error=access_denied&code=")

    def test_authorization_url_asks_for_offline_write_access(self):
        url = google_health.authorization_url("cid", "st", "ch")
        self.assertIn("access_type=offline", url)
        self.assertIn("health_metrics_and_measurements.writeonly", url)
        self.assertIn("code_challenge_method=S256", url)


class HubTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "hub.db")
        self.hub = Hub(self.db)

    def tearDown(self):
        self.db.conn.close()
        self.tmp.cleanup()

    def ingest_capture(self):
        return self.hub.ingest(
            parse_a3_weight(WEIGHT_RAW),
            parse_a3_append(APPEND_RAW),
            WEIGHT_RAW,
            APPEND_RAW,
        )

    def test_scale_time_is_local_wall_clock(self):
        instant, offset = scale_time(529617013)
        local = instant.astimezone()
        self.assertEqual(local.replace(tzinfo=None), datetime(2026, 10, 13, 19, 50, 13))
        self.assertEqual(offset, int(local.utcoffset().total_seconds()))

    def test_capture_is_auto_assigned_with_composition(self):
        me = self.db.create_profile(ME)
        self.db.create_profile(GUEST)
        measurement_id = self.ingest_capture()
        row = self.db.measurement(measurement_id)
        self.assertEqual(row["profile_id"], me)
        self.assertEqual(row["assigned_by"], "auto")
        self.assertAlmostEqual(row["weight_kg"], 97.5)
        self.assertAlmostEqual(row["fat_pct"], 27.4, places=1)
        self.assertEqual(row["google_status"], "none")
        self.assertEqual(row["scale_fat_pct"], 25.2)

    def test_same_weigh_twice_is_stored_once(self):
        self.db.create_profile(ME)
        self.assertIsNotNone(self.ingest_capture())
        self.assertIsNone(self.ingest_capture())

    def test_unmatched_weigh_waits_then_manual_assignment_recomputes(self):
        guest = self.db.create_profile(dict(GUEST, start_weight_kg=60.0))
        measurement_id = self.ingest_capture()
        self.assertIsNone(self.db.measurement(measurement_id)["profile_id"])
        self.hub.assign(measurement_id, guest, by="manual")
        row = self.db.measurement(measurement_id)
        self.assertEqual(row["profile_id"], guest)
        self.assertGreater(row["fat_pct"], 40)

    def test_linked_profile_uploads_weight_and_body_fat(self):
        me = self.db.create_profile(ME)
        self.db.set_setting("google_client_id", "cid")
        self.db.set_setting("google_client_secret", "secret")
        self.db.save_google_link(me, "refresh", "access", 9e12)
        measurement_id = self.ingest_capture()
        self.assertEqual(
            self.db.measurement(measurement_id)["google_status"], "pending"
        )
        calls = []

        async def fake_create(_session, token, data_type, body):
            calls.append((token, data_type, body))
            return {"name": "operations/1"}

        async def run():
            with mock.patch.object(google_health, "create_data_point", fake_create):
                await self.hub.upload(measurement_id)
            await self.hub.close()

        asyncio.run(run())
        self.assertEqual([c[1] for c in calls], ["weight", "body-fat"])
        self.assertEqual(calls[0][2]["weight"]["weightGrams"], 97500)
        row = self.db.measurement(measurement_id)
        self.assertEqual(row["google_status"], "done")
        self.assertEqual(row["google_profile_id"], me)

    def test_failed_upload_is_marked_for_retry(self):
        me = self.db.create_profile(ME)
        self.db.save_google_link(me, "refresh", None, None)
        measurement_id = self.ingest_capture()

        async def run():
            await self.hub.upload(measurement_id)
            await self.hub.close()

        asyncio.run(run())
        row = self.db.measurement(measurement_id)
        self.assertEqual(row["google_status"], "error")
        self.assertIn("OAuth client", row["google_error"])
        self.assertEqual([r["id"] for r in self.db.pending_uploads()], [measurement_id])


class WebTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "hub.db")
        self.hub = Hub(self.db)
        self.client = TestClient(TestServer(create_app(self.hub, NoBluetooth())))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        await self.hub.close()
        self.db.conn.close()
        self.tmp.cleanup()

    async def test_first_visit_goes_to_onboarding(self):
        resp = await self.client.get("/", allow_redirects=False)
        self.assertEqual((resp.status, resp.headers["Location"]), (302, "/welcome"))
        resp = await self.client.post(
            "/welcome",
            data={
                "name": "Me",
                "sex": "male",
                "birth_date": "1990-01-01",
                "height_cm": "183",
                "start_weight_kg": "97.5",
            },
            allow_redirects=False,
        )
        self.assertEqual(resp.headers["Location"], "/welcome/google")
        [profile] = self.db.profiles()
        self.assertEqual(resp.cookies["profile"].value, str(profile["id"]))
        for path in ("/welcome/google", "/welcome/scale"):
            self.assertEqual((await self.client.get(path)).status, 200, path)
        resp = await self.client.get("/welcome", allow_redirects=False)
        self.assertEqual(resp.headers["Location"], "/")

    async def test_pages_render(self):
        me = self.db.create_profile(ME)
        self.db.create_profile(GUEST)
        self.hub.ingest(
            parse_a3_weight(WEIGHT_RAW),
            parse_a3_append(APPEND_RAW),
            WEIGHT_RAW,
            APPEND_RAW,
        )
        for path in (
            "/",
            "/?range=7",
            f"/?p={me}",
            "/history",
            "/history?view=all",
            "/history?view=unassigned",
            "/profiles",
            "/profiles/new",
            f"/profiles/{me}/edit",
            "/settings",
            "/devices",
            "/devices/add",
            "/devices/add?category=Scales",
            "/devices/add?q=dl8780",
            "/api/status",
        ):
            resp = await self.client.get(path)
            self.assertEqual(resp.status, 200, path)
        self.assertIn("97.5", await (await self.client.get("/")).text())

    async def test_unmatched_weigh_asks_who_it_was(self):
        self.db.create_profile(dict(ME, start_weight_kg=80.0))
        self.db.create_profile(dict(GUEST, start_weight_kg=110.0))
        self.hub.ingest(parse_a3_weight(WEIGHT_RAW), None, WEIGHT_RAW, None)
        text = await (await self.client.get("/")).text()
        self.assertIn("Who was this?", text)

    async def test_create_profile_and_reject_invalid(self):
        resp = await self.client.post(
            "/profiles/new",
            data={"name": "", "sex": "x", "birth_date": "", "height_cm": "abc"},
        )
        text = await resp.text()
        self.assertIn("Name is required", text)
        self.assertEqual(self.db.profiles(), [])
        resp = await self.client.post(
            "/profiles/new",
            data={
                "name": "Me",
                "sex": "male",
                "birth_date": "1990-01-01",
                "height_cm": "183",
                "start_weight_kg": "97,5",
            },
        )
        self.assertEqual(resp.status, 200)
        [profile] = self.db.profiles()
        self.assertEqual(profile["start_weight_kg"], 97.5)

    async def test_google_link_needs_client_then_shows_sign_in(self):
        me = self.db.create_profile(ME)
        resp = await self.client.get(f"/profiles/{me}/google", allow_redirects=False)
        self.assertEqual(resp.status, 302)
        self.assertTrue(resp.headers["Location"].startswith("/settings"))
        self.db.set_setting("google_client_id", "cid")
        self.db.set_setting("google_client_secret", "secret")
        resp = await self.client.get(f"/profiles/{me}/google")
        text = await resp.text()
        self.assertIn("accounts.google.com", text)
        self.assertIsNotNone(self.db.oauth_pending_for(me))

    async def test_settings_detour_can_be_left(self):
        # Without an OAuth client, Connect sends the person to Settings. Its back arrow must not
        # lead to the Connect page again, which would bounce straight back to Settings.
        me = self.db.create_profile(ME)
        resp = await self.client.get(
            f"/profiles/{me}/google?next=/profiles/{me}/edit", allow_redirects=False
        )
        settings_url = resp.headers["Location"]
        text = await (await self.client.get(settings_url)).text()
        self.assertIn(
            f'class="icon-btn" href="/profiles/{me}/edit" aria-label="Back"', text
        )
        self.assertIn("Save and continue", text)
        self.db.set_setting("google_client_id", "cid")
        self.db.set_setting("google_client_secret", "secret")
        text = await (await self.client.get(f"/profiles/{me}/google?next=/")).text()
        self.assertIn('href="/">Cancel</a>', text)

    async def test_manual_assignment_from_the_table(self):
        me = self.db.create_profile(dict(ME, start_weight_kg=None))
        measurement_id = self.hub.ingest(
            parse_a3_weight(WEIGHT_RAW), None, WEIGHT_RAW, None
        )
        self.assertIsNone(self.db.measurement(measurement_id)["profile_id"])
        resp = await self.client.post(
            f"/measurements/{measurement_id}/assign", data={"profile_id": str(me)}
        )
        self.assertEqual(resp.status, 200)
        self.assertEqual(self.db.measurement(measurement_id)["profile_id"], me)


class DeviceWebTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "hub.db")
        self.hub = Hub(self.db)
        self.listener = PairedListener()
        self.client = TestClient(TestServer(create_app(self.hub, self.listener)))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        await self.hub.close()
        self.db.conn.close()
        self.tmp.cleanup()

    async def test_hub_lists_the_scale_and_nearby_pairing(self):
        self.assertIn(
            "Bathroom scale", await (await self.client.get("/devices")).text()
        )
        text = await (await self.client.get("/devices/add")).text()
        self.assertIn("Ready to pair", text)
        resp = await self.client.post(
            "/devices/pair", data={"next": "/devices/add"}, allow_redirects=False
        )
        self.assertEqual(resp.headers["Location"], "/devices/add")
        self.assertTrue(self.listener.pairing)
        self.assertIn(
            "Waiting for the scale",
            await (await self.client.get("/devices/add")).text(),
        )

    async def test_rename_and_forget(self):
        await self.client.post(
            "/devices/scale", data={"name": "Upstairs scale", "room": "Bedroom"}
        )
        text = await (await self.client.get("/devices/scale")).text()
        self.assertIn("Upstairs scale", text)
        self.assertIn("Bedroom", text)
        await self.client.post("/devices/scale/forget")
        self.assertTrue(self.listener.forgotten)

    async def test_redirect_targets_stay_on_this_site(self):
        self.db.create_profile(ME)
        measurement_id = self.hub.ingest(
            parse_a3_weight(WEIGHT_RAW), None, WEIGHT_RAW, None
        )
        resp = await self.client.post(
            f"/measurements/{measurement_id}/retry",
            data={"next": "//evil.example"},
            allow_redirects=False,
        )
        self.assertTrue(resp.headers["Location"].startswith("/?"))


if __name__ == "__main__":
    unittest.main()
