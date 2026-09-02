from backend.gemini import _canonical_youtube_url, _generation_config


def test_canonical_youtube_url_removes_timestamp():
    assert _canonical_youtube_url(
        "https://www.youtube.com/watch?v=8_vkp_IbFmk&t=644s"
    ) == "https://www.youtube.com/watch?v=8_vkp_IbFmk"
    assert _canonical_youtube_url(
        "https://youtu.be/8_vkp_IbFmk?t=644"
    ) == "https://www.youtube.com/watch?v=8_vkp_IbFmk"


def test_gemini_36_config_omits_unsupported_schema_and_sampling_parameters():
    config = _generation_config()
    assert config.response_mime_type == "application/json"
    assert config.response_schema is None
    assert config.response_json_schema is None
    assert config.temperature is None
    assert config.top_p is None
    assert config.top_k is None
