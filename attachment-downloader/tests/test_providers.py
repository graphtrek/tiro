import pytest
from attachment_downloader.base import EmailClient
from attachment_downloader.providers import get_client


def test_get_client_gmail_satisfies_protocol():
    from unittest.mock import patch
    with patch('attachment_downloader.providers.gmail.client.build'):
        c = get_client("gmail")
    assert isinstance(c, EmailClient)


def test_get_client_unknown_raises():
    with pytest.raises(ValueError, match="Unknown provider"):
        get_client("outlook")
