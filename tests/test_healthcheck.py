"""The /healthz endpoint must answer a load balancer before host/TLS checks.

A load-balancer health check cannot control the Host header it sends, so the
endpoint has to return 200 even for a Host that is not in ALLOWED_HOSTS and
without the HTTPS that SECURE_SSL_REDIRECT would otherwise demand — otherwise
the target is marked unhealthy and never receives traffic.
"""

import pytest
from django.test import Client


@pytest.mark.parametrize(
    "host",
    [
        "testserver",  # an allowed host
        "10.0.1.23",  # a target private IP, as an ALB health check sends
        "anything.example",  # not in ALLOWED_HOSTS at all
    ],
)
def test_healthz_ok_regardless_of_host(host):
    # SECURE_SSL_REDIRECT is off under the test settings (DEBUG path), so this
    # isolates the host-validation bypass; the redirect bypass is covered below.
    response = Client().get("/healthz", HTTP_HOST=host)
    assert response.status_code == 200
    assert response.content == b"ok"


def test_healthz_not_redirected_to_https(settings):
    settings.SECURE_SSL_REDIRECT = True
    # An insecure request to any other path would 301 to https; /healthz must not.
    response = Client().get("/healthz", secure=False)
    assert response.status_code == 200
