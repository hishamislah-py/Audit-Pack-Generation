"""Column/field name normalisation used for tier-3 matching and fingerprints."""
import re
import unicodedata

_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_NON_ALNUM = re.compile(r"[^0-9a-z]+")


def normalise_name(name: str) -> str:
    """'Client ID' / 'client-id' / 'ClientId' / ' CLIENT_ID ' -> 'client_id'."""
    s = unicodedata.normalize("NFKC", name).replace("\ufeff", "").strip()
    s = s.replace("&", " and ").replace("#", " number ")
    s = _CAMEL.sub("_", s).lower()
    return _NON_ALNUM.sub("_", s).strip("_")
