"""REQUIREMENTS acceptance criterion: each service answers GET /health without authentication."""
import requests


def test_all_services_health(base_urls):
    failures = []
    for name, base in base_urls.items():
        try:
            resp = requests.get(f"{base}/health", timeout=5)
        except requests.RequestException as exc:
            failures.append(f"{name}: request failed ({exc})")
            continue
        if resp.status_code != 200:
            failures.append(f"{name}: got {resp.status_code}, body={resp.text[:200]!r}")
    assert not failures, "\n".join(failures)
