"""Runtime patch for a base64 padding bug in firebase-messaging.

firebase-messaging 0.4.5 (the latest release at the time of writing) decodes
the ``crypto-key`` and ``encryption`` headers of an incoming push without
correcting the base64 padding::

    crypto_key = urlsafe_b64decode(crypto_key_str.encode("ascii"))   # line 378
    salt = urlsafe_b64decode(salt_str.encode("ascii"))

Two lines below it pads the *stored* keys defensively (``+ b"========"``) but
not these two, which come from the message itself. When they arrive unpadded
the decode raises ``binascii.Error: Incorrect padding``. ``_listen`` catches
that generically and shuts the whole client down, and because the message is
never acked the server redelivers it on the next connection -- wedging the
client in a permanent crash/reconnect loop that no amount of restarting can
clear.

This patch pads both values before decoding. It also stops an undecryptable
message from tearing down the connection: returning empty bytes makes the
library log a decrypt failure and move on, so the message is acked and never
redelivered.
"""

import logging
import string

_LOGGER = logging.getLogger(__name__)

_PATCH_FLAG = "_aqualisa_padding_patched"
_LOG_FLAG = "_aqualisa_header_logging"

_B64URL_CHARS = frozenset(string.ascii_letters + string.digits + "-_=")

# Headers worth dumping when decryption fails. The values are public key
# material and a salt, not secrets.
_INTERESTING_HEADERS = ("crypto-key", "encryption", "content-encoding", "subtype")


def _pad(value: str) -> str:
    """Restore base64 padding that the sender stripped."""
    if not isinstance(value, str):
        return value
    return value + "=" * (-len(value) % 4)


def _describe(label: str, value) -> str:
    """Summarise a base64 field for diagnostics without dumping it wholesale."""
    if not isinstance(value, str):
        return f"{label}=<{type(value).__name__}>"
    unexpected = "".join(sorted({c for c in value if c not in _B64URL_CHARS}))
    return (
        f"{label}: len={len(value)} len%4={len(value) % 4} "
        f"head={value[:12]!r} tail={value[-6:]!r} unexpected_chars={unexpected!r}"
    )


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
            _LOGGER.warning(
                "Skipping undecryptable push message (%s | %s | raw_data len=%s)",
                _describe("crypto_key", crypto_key_str),
                _describe("salt", salt_str),
                len(raw_data) if raw_data is not None else None,
                exc_info=True,
            )
            return b""

    setattr(_decrypt_raw_data, _PATCH_FLAG, True)
    FcmPushClient._decrypt_raw_data = staticmethod(_decrypt_raw_data)
    _LOGGER.debug("Applied firebase-messaging base64 padding patch")


def extract_param(value: str, name: str) -> str | None:
    """Pull one parameter out of a semicolon-separated header value.

    ``crypto-key: dh=<key>; p256ecdsa=<vapid key>`` -> ``extract_param(v, "dh")``
    returns just the ``dh`` value. Returns None when the header carries a bare
    value with no ``name=`` prefix, so the caller can leave it alone.
    """
    if not isinstance(value, str):
        return None
    for part in value.split(";"):
        key, sep, val = part.strip().partition("=")
        if sep and key.strip().lower() == name:
            return val.strip()
    return None


def apply_fcm_header_fix() -> None:
    """Normalise push headers so the library's fixed-offset slicing is correct.

    firebase-messaging extracts the encryption parameters by slicing a constant
    number of characters::

        crypto_key = self._app_data_by_key(msg, "crypto-key")[3:]  # strip dh=
        salt = self._app_data_by_key(msg, "encryption")[5:]        # strip salt=

    That assumes each header holds exactly one parameter. Aqualisa sends
    ``crypto-key: dh=<key>; p256ecdsa=<vapid key>``, so the slice keeps the
    VAPID parameter too. base64 decoding silently drops the ``;`` and space and
    folds the second key into the output, producing roughly 139 bytes of
    nonsense rather than a 65 byte P-256 point -- and the stray ``=`` from
    ``p256ecdsa=`` is what raised "Incorrect padding" in the first place.

    Rewriting each header down to the single parameter the library expects
    makes its own slicing land correctly, without having to reimplement
    _handle_data_message.
    """
    try:
        from firebase_messaging import FcmPushClient
    except ImportError:  # pragma: no cover
        return

    original = FcmPushClient.__dict__.get("_app_data_by_key")
    if original is None or getattr(original, _LOG_FLAG, False):
        return

    wanted = {"crypto-key": "dh", "encryption": "salt"}

    def _app_data_by_key(self, p, key, do_not_raise: bool = False) -> str:
        value = original(self, p, key, do_not_raise)
        if key in _INTERESTING_HEADERS and _LOGGER.isEnabledFor(logging.DEBUG):
            _LOGGER.debug("push header %r = %r", key, value)
        if (name := wanted.get(key)) and (found := extract_param(value, name)) is not None:
            normalised = f"{name}={found}"
            if normalised != value:
                _LOGGER.debug("normalised %r header to %r", key, f"{name}=...")
            return normalised
        return value

    setattr(_app_data_by_key, _LOG_FLAG, True)
    FcmPushClient._app_data_by_key = _app_data_by_key
    _LOGGER.debug("Applied firebase-messaging header parameter fix")
