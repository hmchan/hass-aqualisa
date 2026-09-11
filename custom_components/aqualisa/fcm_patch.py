"""Runtime patch for a base64 padding bug in firebase-messaging.

firebase-messaging 0.4.5 (the latest release at the time of writing) decodes
the ``crypto-key`` and ``encryption`` headers of an incoming push without
correcting the base64 padding::

    crypto_key = urlsafe_b64decode(crypto_key_str.encode("ascii"))   # line 378
    salt = urlsafe_b64decode(salt_str.encode("ascii"))

Two lines below it pads the *stored* keys defensively (``+ b"========"``) but
not these two, which come from the message itself. Aqualisa's push service
sends them unpadded, so the decode raises ``binascii.Error: Incorrect
padding``. ``_listen`` catches that generically and shuts the whole client
down, and because the message is never acked the server redelivers it on the
next connection -- wedging the client in a permanent crash/reconnect loop that
no amount of restarting can clear.

This patch pads both values before decoding. It also stops an undecryptable
message from tearing down the connection: returning empty bytes makes the
library log a decrypt failure and move on, so the message is acked and never
redelivered.
"""

import logging

_LOGGER = logging.getLogger(__name__)

_PATCH_FLAG = "_aqualisa_padding_patched"


def _pad(value: str) -> str:
    """Restore base64 padding that the sender stripped."""
    if not isinstance(value, str):
        return value
    return value + "=" * (-len(value) % 4)


def apply_fcm_padding_patch() -> None:
    """Patch FcmPushClient._decrypt_raw_data. Safe to call more than once."""
    try:
        from firebase_messaging import FcmPushClient
    except ImportError:  # pragma: no cover - dependency is declared in the manifest
        _LOGGER.warning("firebase_messaging not importable, skipping padding patch")
        return

    raw = FcmPushClient.__dict__.get("_decrypt_raw_data")
    if raw is None:
        _LOGGER.warning(
            "firebase_messaging has no _decrypt_raw_data, skipping padding patch"
        )
        return

    original = getattr(raw, "__func__", raw)
    if getattr(original, _PATCH_FLAG, False):
        return

    def _decrypt_raw_data(credentials, crypto_key_str, salt_str, raw_data):
        try:
            return original(credentials, _pad(crypto_key_str), _pad(salt_str), raw_data)
        except Exception:
            # Never propagate. An exception here reaches _listen, which shuts the
            # client down, and the unacked message is then redelivered forever.
            _LOGGER.warning("Skipping undecryptable push message", exc_info=True)
            return b""

    setattr(_decrypt_raw_data, _PATCH_FLAG, True)
    FcmPushClient._decrypt_raw_data = staticmethod(_decrypt_raw_data)
    _LOGGER.debug("Applied firebase-messaging base64 padding patch")
