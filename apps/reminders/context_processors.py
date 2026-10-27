from .services import unread_count


def notifications(request):
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated and user.is_student:
        return {"unread_notifications": unread_count(user)}
    return {}
