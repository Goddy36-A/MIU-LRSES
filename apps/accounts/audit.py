from .models import AuditLog


def client_ip(request):
    if request is None:
        return None
    return request.META.get("REMOTE_ADDR") or None


def log_action(action, actor=None, target="", details="", request=None):
    """Write one audit entry. Never stores passwords or tokens."""
    if actor is not None and not getattr(actor, "is_authenticated", False):
        actor = None
    return AuditLog.objects.create(
        actor=actor,
        actor_label=getattr(actor, "username", "") if actor else "",
        action=action,
        target=str(target)[:255],
        details=details,
        ip_address=client_ip(request),
    )
