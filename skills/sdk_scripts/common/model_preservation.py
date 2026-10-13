"""Raw-field identity checks shared by scoped equipment transactions."""

import hashlib
import json


def fingerprint(obj, tokens=None, ignored=(), field_limit=None):
    raw = obj.idfObject()
    fields = []
    for i in range(raw.numFields() if field_limit is None else field_limit):
        field = raw.iddObject().getField(i)
        name = field.get().name() if field.is_initialized() else str(i)
        if name in ignored:
            continue
        value = raw.getString(i)
        value = value.get() if value.is_initialized() else ""
        fields.append((i, (tokens or {}).get(value, value)))
    return hashlib.sha256(json.dumps(fields, ensure_ascii=True).encode()).hexdigest()


def snapshot(model, *, excluded=(), ignored=None, field_limits=None):
    # Existing companion packaging may materialize the empty weather singleton.
    model.getWeatherFile()
    result = {}
    for obj in model.modelObjects():
        handle = str(obj.handle())
        if handle in excluded:
            continue
        kind = obj.iddObjectType().valueName()
        omitted = tuple((ignored or {}).get(handle, ()))
        key = handle
        if kind == "OS_WeatherFile":
            key = "@weather"
            omitted += ("Handle", "Url", "Checksum")
        elif kind == "OS_External_File":
            omitted += ("File Name",)
        if key in result:
            raise ValueError("Duplicate protected object identity")
        result[key] = fingerprint(
            obj, ignored=omitted, field_limit=(field_limits or {}).get(handle)
        )
    return result
