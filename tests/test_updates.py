from hashlib import sha256
from io import BytesIO

import pytest

from endurance.updates import download, release_offer


def release(body=b"installer", tag="v0.10.0"):
    name = f"IRacingTools-{tag[1:]}-windows-x64-setup.exe"
    return {"tag_name": tag, "assets": [{"name": name, "size": len(body),
                                          "digest": f"sha256:{sha256(body).hexdigest()}",
                                          "browser_download_url": "https://example.com/untrusted"}]}


def test_release_uses_numeric_versions_and_its_own_repo():
    offer = release_offer(release(), "0.9.0", combined=True)
    assert offer.version == "0.10.0"
    assert offer.url == ("https://github.com/XiaoyangSu-Sam/ir_setup_helper/releases/download/v0.10.0/"
                         "IRacingTools-0.10.0-windows-x64-setup.exe")
    assert release_offer(release(), "0.10.0", combined=True) is None
    assert release_offer(release(), "0.11.0", combined=True) is None
    with pytest.raises(ValueError):
        release_offer(release(tag="v0.10.0-preview"), "0.9.0", combined=True)
    with pytest.raises(ValueError):
        release_offer(release(), "0.9.0", combined=False)


def test_download_publishes_only_a_verified_complete_installer(tmp_path, monkeypatch):
    offer = release_offer(release(), "0.9.0", combined=True)
    monkeypatch.setattr("endurance.updates.urlopen", lambda *args, **kwargs: BytesIO(b"different"))
    with pytest.raises(ValueError, match="校验"):
        download(offer, tmp_path)
    assert not list(tmp_path.iterdir())
    monkeypatch.setattr("endurance.updates.urlopen", lambda *args, **kwargs: BytesIO(b"installer"))
    path = download(offer, tmp_path)
    assert path.read_bytes() == b"installer"
    assert list(tmp_path.iterdir()) == [path]
