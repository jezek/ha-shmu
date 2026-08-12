import importlib.util
from pathlib import Path
import sys
import unittest


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "custom_components"
    / "shmu"
    / "location_catalog.py"
)


def _load_module():
    spec = importlib.util.spec_from_file_location("shmu_location_catalog", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class _Response:
    def __init__(self, text, status=200):
        self.status = status
        self._text = text

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def text(self):
        return self._text


class _Session:
    def __init__(self, responses):
        self._responses = iter(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return next(self._responses)


class TestLocationCatalog(unittest.IsolatedAsyncioTestCase):
    def test_parse_selector_options_targets_named_select(self):
        module = _load_module()
        html = """
            <select name="ignored"><option value="9">Wrong</option></select>
            <select id="station_id" name="station_id">
              <option value="11815"> Pezinok - Grinava </option>
              <option value="">Choose</option>
            </select>
        """

        self.assertEqual(
            module.parse_selector_options(html, "station_id"),
            [module.LocationOption("11815", "Pezinok - Grinava")],
        )

    def test_pezinok_location_resolves_one_station(self):
        module = _load_module()
        stations = [
            module.LocationOption("11815", "Pezinok - Grinava"),
            module.LocationOption("11833", "Modra - Piesok"),
        ]

        result = module.station_candidates_for_location(
            module.LocationOption("31396", "Pezinok"), stations
        )

        self.assertEqual(result, [stations[0]])

    def test_ambiguous_locality_keeps_all_dependent_station_choices(self):
        module = _load_module()
        stations = [
            module.LocationOption("11813", "Bratislava - Koliba"),
            module.LocationOption("11816", "Bratislava - Letisko"),
            module.LocationOption("11810", "Bratislava - Mlynská Dolina"),
        ]

        result = module.station_candidates_for_location(
            module.LocationOption("32737", "Bratislava (centrum)"), stations
        )

        self.assertEqual(result, stations)

    def test_location_query_prefers_exact_match(self):
        module = _load_module()
        locations = [
            module.LocationOption("31396", "Pezinok"),
            module.LocationOption("31581", "Pezinska Baba"),
        ]

        self.assertEqual(
            module.location_candidates_for_query("  PEZINOK ", locations),
            [locations[0]],
        )

    def test_location_query_returns_small_ambiguous_subset(self):
        module = _load_module()
        locations = [
            module.LocationOption("31176", "Bratislava - Koliba"),
            module.LocationOption("32737", "Bratislava (centrum)"),
            module.LocationOption("31396", "Pezinok"),
        ]

        self.assertEqual(
            module.location_candidates_for_query("Bratislava", locations),
            locations[:2],
        )

    async def test_fetch_catalog_uses_official_selectors_and_ssl_setting(self):
        module = _load_module()
        session = _Session(
            [
                _Response('<select name="station_id"><option value="11815">Pezinok - Grinava</option></select>'),
                _Response('<select name="nwp_mesto"><option value="31396">Pezinok</option></select>'),
            ]
        )

        stations, locations = await module.async_fetch_location_catalog(
            session, verify_ssl=False
        )

        self.assertEqual(stations[0].value, "11815")
        self.assertEqual(locations[0].value, "31396")
        self.assertEqual(len(session.calls), 2)
        self.assertTrue(all(kwargs == {"ssl": False} for _, kwargs in session.calls))

    async def test_fetch_catalog_reports_http_error(self):
        module = _load_module()
        session = _Session([_Response("", status=503)])

        with self.assertRaisesRegex(ValueError, "HTTP 503"):
            await module.async_fetch_location_catalog(session)
