import importlib.util
from pathlib import Path
import sys
import types
import unittest


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "custom_components"
    / "shmu"
    / "api.py"
)


def _load_api():
    custom_components = types.ModuleType("custom_components")
    shmu = types.ModuleType("custom_components.shmu")
    custom_components.__path__ = [str(MODULE_PATH.parents[2])]
    shmu.__path__ = [str(MODULE_PATH.parent)]
    sys.modules.setdefault("custom_components", custom_components)
    sys.modules.setdefault("custom_components.shmu", shmu)
    sys.modules["aiohttp"] = _aiohttp_stub()
    sys.modules["async_timeout"] = _async_timeout_stub()

    spec = importlib.util.spec_from_file_location(
        "custom_components.shmu.api",
        MODULE_PATH,
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _aiohttp_stub():
    module = types.ModuleType("aiohttp")

    class ClientError(Exception):
        pass

    class ClientSession:
        pass

    module.ClientError = ClientError
    module.ClientSession = ClientSession
    return module


def _async_timeout_stub():
    module = types.ModuleType("async_timeout")

    class _Timeout:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

    module.timeout = lambda seconds: _Timeout()
    return module


class _Response:
    def __init__(self, status=200, payload=None):
        self.status = status
        self._payload = payload if payload is not None else {"data": []}

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def json(self):
        return self._payload


class _Session:
    def __init__(self, response):
        self._response = response
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self._response


class TestSHMUAPI(unittest.IsolatedAsyncioTestCase):
    async def test_fetch_data_uses_supplied_session(self):
        api_module = _load_api()
        api = api_module.SHMUAPI("11813")
        api._generate_url = lambda: "https://example.test/current.json"
        session = _Session(
            _Response(
                payload={
                    "data": [
                        {"ind_kli": "99999", "t": 1.0},
                        {"ind_kli": "11813", "t": 21.5},
                    ]
                }
            )
        )

        result = await api.fetch_data(session)

        self.assertEqual(result, {"ind_kli": "11813", "t": 21.5})
        self.assertEqual(session.calls, [("https://example.test/current.json", {})])

    async def test_fetch_data_passes_ssl_false_when_verification_disabled(self):
        api_module = _load_api()
        api = api_module.SHMUAPI("11813", verify_ssl=False)
        api._generate_url = lambda: "https://example.test/current.json"
        session = _Session(_Response(payload={"data": [{"ind_kli": "11813"}]}))

        await api.fetch_data(session)

        self.assertEqual(
            session.calls,
            [("https://example.test/current.json", {"ssl": False})],
        )

    async def test_fetch_data_reports_http_status(self):
        api_module = _load_api()
        api = api_module.SHMUAPI("11813")
        api._generate_url = lambda: "https://example.test/current.json"
        session = _Session(_Response(status=404))

        with self.assertRaisesRegex(Exception, "HTTP 404"):
            await api.fetch_data(session)


if __name__ == "__main__":
    unittest.main()
