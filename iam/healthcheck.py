from django.http import HttpResponse


class HealthCheckMiddleware:
    """Answer the load-balancer health check before any host or TLS check runs.

    A load balancer's target-group health check (e.g. an AWS ALB) cannot set the
    Host header it sends — it uses the target's own private IP — so the probe
    would be rejected by ALLOWED_HOSTS with HTTP 400 before reaching any view,
    and SecurityMiddleware's HTTPS redirect would 301 it first regardless. Placed
    at the very top of MIDDLEWARE, this short-circuits one fixed path with a
    static body: it never calls request.get_host() and never touches the
    database, so it leaks nothing and gives the load balancer a stable 200 to
    probe. Every other path falls through untouched to the normal stack.
    """

    health_check_path = "/healthz"

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path == self.health_check_path:
            return HttpResponse("ok", content_type="text/plain")
        return self.get_response(request)
