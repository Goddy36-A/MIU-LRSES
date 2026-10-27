"""Delivery channels.

Only ``in_app`` exists. For an in-app notification the Notification row itself *is* the delivery: the
recipient sees it in their notification list once its status is Delivered. No browser push, email, SMS,
WhatsApp or Telegram message is sent by this system.

To add a channel later: subclass DeliveryChannel, implement ``send`` (raise an exception on failure),
register it with ``register_channel`` and list its name in settings.REMINDER_CHANNELS. A reminder is
Delivered only when every configured channel succeeded; otherwise it is marked Failed and retried.
"""
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


class DeliveryChannel:
    name = ""

    def send(self, notification):
        raise NotImplementedError


class InAppChannel(DeliveryChannel):
    name = "in_app"

    def send(self, notification):
        return None  # nothing to push: the stored notification is what the recipient reads


CHANNEL_REGISTRY = {InAppChannel.name: InAppChannel}


def register_channel(channel_class):
    CHANNEL_REGISTRY[channel_class.name] = channel_class
    return channel_class


def get_channels():
    names = getattr(settings, "REMINDER_CHANNELS", ["in_app"])
    channels = []
    for name in names:
        try:
            channels.append(CHANNEL_REGISTRY[name]())
        except KeyError:
            raise ImproperlyConfigured(f"Unknown reminder channel '{name}'. Registered: {sorted(CHANNEL_REGISTRY)}")
    return channels
