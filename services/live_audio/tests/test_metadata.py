from live_audio.metadata import MetadataConfig, load_site_and_channel_names


def test_resolve_uses_raw_site_and_channel_by_default():
    config = MetadataConfig()
    meta = config.resolve("home", "WX5")
    assert meta.name == "Tocsin home WX5"
    assert meta.description == "Tocsin NOAA Weather Radio relay"
    assert meta.genre == "weather"


def test_resolve_applies_display_name_overrides():
    config = MetadataConfig(site_names={"home": "Portland Home Station"}, channel_names={"WX5": "Channel 5"})
    meta = config.resolve("home", "WX5")
    assert meta.name == "Tocsin Portland Home Station Channel 5"


def test_resolve_falls_back_to_raw_name_for_unmapped_site_or_channel():
    config = MetadataConfig(site_names={"home": "Portland Home Station"})
    meta = config.resolve("home", "WX5")
    assert meta.name == "Tocsin Portland Home Station WX5"


def test_custom_template_and_description_and_genre():
    config = MetadataConfig(name_template="{site}/{channel}", description="custom desc", genre="custom genre")
    meta = config.resolve("home", "WX5")
    assert meta.name == "home/WX5"
    assert meta.description == "custom desc"
    assert meta.genre == "custom genre"


def test_load_site_and_channel_names_returns_empty_when_path_is_none():
    assert load_site_and_channel_names(None) == ({}, {})


def test_load_site_and_channel_names_reads_yaml_file(tmp_path):
    config_file = tmp_path / "metadata.yaml"
    config_file.write_text(
        "site_names:\n"
        "  home: Portland Home Station\n"
        "channel_names:\n"
        "  WX5: Channel 5\n"
    )
    site_names, channel_names = load_site_and_channel_names(config_file)
    assert site_names == {"home": "Portland Home Station"}
    assert channel_names == {"WX5": "Channel 5"}


def test_load_site_and_channel_names_handles_missing_sections(tmp_path):
    config_file = tmp_path / "metadata.yaml"
    config_file.write_text("site_names:\n  home: Portland Home Station\n")
    site_names, channel_names = load_site_and_channel_names(config_file)
    assert site_names == {"home": "Portland Home Station"}
    assert channel_names == {}


def test_load_site_and_channel_names_handles_empty_file(tmp_path):
    config_file = tmp_path / "metadata.yaml"
    config_file.write_text("")
    assert load_site_and_channel_names(config_file) == ({}, {})
