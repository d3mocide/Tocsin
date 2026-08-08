import json

from api.spectrum import get_spectrum, list_spectrum_sites


class FakeRedis:
    def __init__(self, store=None):
        self.store = store or {}

    async def get(self, key):
        return self.store.get(key)

    async def keys(self, pattern):
        prefix = pattern.rstrip("*")
        return [k for k in self.store if k.startswith(prefix)]


async def test_get_spectrum_returns_the_decoded_snapshot():
    redis = FakeRedis({"tocsin:spectrum:home": json.dumps({"site": "home", "bin_power_db": [-40.0]})})
    snapshot = await get_spectrum(redis, "home")
    assert snapshot == {"site": "home", "bin_power_db": [-40.0]}


async def test_get_spectrum_returns_none_when_missing():
    redis = FakeRedis()
    assert await get_spectrum(redis, "home") is None


async def test_list_spectrum_sites_strips_the_key_prefix():
    redis = FakeRedis(
        {
            "tocsin:spectrum:home": json.dumps({"site": "home"}),
            "tocsin:spectrum:office": json.dumps({"site": "office"}),
        }
    )
    sites = await list_spectrum_sites(redis)
    assert set(sites) == {"home", "office"}
