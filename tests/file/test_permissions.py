import pytest
from unittest.mock import patch
from dorsal.file.permissions import is_permitted_public_media_type


@pytest.mark.parametrize("invalid_input", [None, 123, [], {}, 1.5, True])
def test_returns_false_for_non_string_inputs(invalid_input):
    """Ensures the function handles non-string inputs gracefully."""
    assert is_permitted_public_media_type(invalid_input) is False


@pytest.mark.parametrize(
    "malformed_media_type",
    ["plain", "/plain", "text/", "text / plain", "text/plain;", "text/plain, ", "text/plain version=1"],
)
def test_returns_false_for_malformed_strings(malformed_media_type):
    """Ensures the regex validation rejects invalid MIME type formats."""
    assert is_permitted_public_media_type(malformed_media_type) is False


@pytest.mark.parametrize(
    "permitted_type",
    [
        "text/plain",
        "text/markdown",
        "application/pdf",
        "application/zip",
        "application/atom+xml",
        "application/vnd.amazon.ebook",
    ],
)
def test_returns_true_for_explicitly_permitted_types(permitted_type):
    """Tests exact matches against the MEDIA_TYPE_PERMITTED set."""
    assert is_permitted_public_media_type(permitted_type) is True


@pytest.mark.parametrize(
    "head_permitted_type",
    [
        "image/png",
        "image/jpeg",
        "image/custom-format",
        "video/mp4",
        "audio/mpeg",
        "font/woff2",
    ],
)
def test_returns_true_for_permitted_heads(head_permitted_type):
    """Tests types allowed because their 'head' (image, video, etc) is permitted."""
    assert is_permitted_public_media_type(head_permitted_type) is True


@pytest.mark.parametrize("media_type", ["TEXT/PLAIN", "Application/PDF", "IMAGE/Jpeg", "Video/MP4"])
def test_is_case_insensitive(media_type):
    """Ensures input is normalized to lowercase before checking lists."""
    assert is_permitted_public_media_type(media_type) is True


@pytest.mark.parametrize(
    "denied_type",
    [
        "text/html",
        "application/octet-stream",
        "application/javascript",
        "chemical/x-pdb",
    ],
)
def test_returns_false_for_unlisted_types(denied_type):
    """Tests valid MIME formats that are simply not in the allow lists."""
    assert is_permitted_public_media_type(denied_type) is False


def test_respects_prohibited_list_patch():
    """
    Verify that if a type is added to PUBLIC_MEDIA_TYPES_PROHIBITED via patch,
    it returns False even if it is otherwise permitted.
    """
    assert is_permitted_public_media_type("text/plain") is True

    with patch("dorsal.file.permissions.PUBLIC_MEDIA_TYPES_PROHIBITED", {"text/plain"}):
        assert is_permitted_public_media_type("text/plain") is False
