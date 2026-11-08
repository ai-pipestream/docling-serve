"""Typed OCR options: proto oneof to the dict jobkit splats, and back.

Slim stores engine settings on ``OcrOptions`` subclasses. Serve still carries
them as ``ocr_custom_config`` plus a ``kind``. The oneof is the primary wire
form. ``ocr_custom_config`` remains only for keys that message does not define.

Precedence when the oneof is set:

* A key that the selected message defines is owned by that message. The same
  key in ``ocr_custom_config`` is an error. The map does not override it.
* Keys the message does not define are copied from the map.
* ``kind`` in the map must match the arm. A different kind is an error.
* ``ocr_engine``, when set, must be that same kind. It is not also written,
  because the request model would copy it onto ``ocr_preset`` and then reject
  the custom config.
* A non-auto ``ocr_preset`` is an error.
* ``ocr_lang`` is written as ``lang`` only when the arm left ``lang`` unset.
  Both set is an error.

Unset optional fields are omitted. Explicit false is written as false. An
empty ``OcrLang`` is an empty list. An omitted ``OcrLang`` leaves the engine
class default alone.
"""

from __future__ import annotations

import enum
from typing import Optional

from google.protobuf.descriptor import FieldDescriptor

from .gen.ai.docling.serve.v1 import docling_serve_types_pb2 as pb2

# Proto oneof arm -> factory kind (the Pydantic ClassVar, not OcrEngine).
_ARM_KIND = {
    "ocr_auto": "auto",
    "easyocr": "easyocr",
    "tesseract": "tesserocr",
    "tesseract_cli": "tesseract",
    "rapidocr": "rapidocr",
    "ocrmac": "ocrmac",
    "nemotron_ocr": "nemotron-ocr",
    "kserve_v2_ocr": "kserve_v2_ocr",
}
_KIND_TO_ARM = {kind: arm for arm, kind in _ARM_KIND.items()}

_OCR_MODE_FROM_NAME = {
    "OCR_MODE_FULL_PAGE": "full_page",
    "OCR_MODE_LAYOUT_REGIONS": "layout_regions",
    "OCR_MODE_PDF_AWARE_LAYOUT_REGIONS": "pdf_aware_layout_regions",
    "OCR_MODE_DEFAULT": "default",
}
_RAPID_BACKEND_FROM_NAME = {
    "RAPID_OCR_BACKEND_ONNXRUNTIME": "onnxruntime",
    "RAPID_OCR_BACKEND_OPENVINO": "openvino",
    "RAPID_OCR_BACKEND_PADDLE": "paddle",
    "RAPID_OCR_BACKEND_TORCH": "torch",
}
_RAPID_MODEL_SIZE_FROM_NAME = {
    "RAPID_OCR_MODEL_SIZE_TINY": "tiny",
    "RAPID_OCR_MODEL_SIZE_SMALL": "small",
    "RAPID_OCR_MODEL_SIZE_MEDIUM": "medium",
}
_NEMOTRON_MERGE_FROM_NAME = {
    "NEMOTRON_OCR_MERGE_LEVEL_WORD": "word",
    "NEMOTRON_OCR_MERGE_LEVEL_SENTENCE": "sentence",
    "NEMOTRON_OCR_MERGE_LEVEL_PARAGRAPH": "paragraph",
}
_KSERVE_TRANSPORT_FROM_NAME = {
    "KSERVE_V2_TRANSPORT_GRPC": "grpc",
    "KSERVE_V2_TRANSPORT_HTTP": "http",
}

_ENUM_FROM_NAME = {
    "mode": _OCR_MODE_FROM_NAME,
    "backend": _RAPID_BACKEND_FROM_NAME,
    "model_size": _RAPID_MODEL_SIZE_FROM_NAME,
    "merge_level": _NEMOTRON_MERGE_FROM_NAME,
    "transport": _KSERVE_TRANSPORT_FROM_NAME,
}
_ENUM_TO_TAG = {
    field: {value: getattr(pb2, name) for name, value in mapping.items()}
    for field, mapping in _ENUM_FROM_NAME.items()
}

_INT64_MAX = (1 << 63) - 1
_INT64_MIN = -(1 << 63)
_UINT64_MAX = (1 << 64) - 1


def ocr_kind_to_arm() -> dict[str, str]:
    """Factory kind string to ``ConvertDocumentOptions.ocr_options`` arm."""
    return dict(_KIND_TO_ARM)


def _enum_value_name(field: FieldDescriptor, number: int) -> Optional[str]:
    if number == 0:
        return None
    try:
        return field.enum_type.values_by_number[number].name
    except KeyError:
        return None


def _closed_literal(
    message, enum_field: str, raw_field: str, label: str
) -> Optional[str]:
    """Read an optional enum plus ``*_raw``. Unset is None. Disagreement errors."""
    has_enum = message.HasField(enum_field)
    has_raw = message.HasField(raw_field)
    if not has_enum and not has_raw:
        return None
    raw = getattr(message, raw_field) if has_raw else ""
    if not has_enum:
        if not raw:
            raise ValueError(f"{label}_raw is empty")
        return raw
    field = message.DESCRIPTOR.fields_by_name[enum_field]
    name = _enum_value_name(field, getattr(message, enum_field))
    if name is None:
        if raw:
            return raw
        raise ValueError(f"{label} is unspecified")
    value = _ENUM_FROM_NAME[enum_field].get(name)
    if value is None:
        raise ValueError(f"{label} is not a known value")
    if has_raw and raw != value:
        raise ValueError(f"{label} and {raw_field} disagree")
    return value


def _scalar_to_python(value: pb2.ScalarValue):
    kind = value.WhichOneof("kind")
    if kind == "string_value":
        return value.string_value
    if kind == "int_value":
        return value.int_value
    if kind == "double_value":
        return value.double_value
    if kind == "bool_value":
        return value.bool_value
    if kind == "uint_value":
        return value.uint_value
    return None


def _python_to_scalar(value) -> Optional[pb2.ScalarValue]:
    message = pb2.ScalarValue()
    if isinstance(value, bool):
        message.bool_value = value
    elif isinstance(value, int):
        if _INT64_MIN <= value <= _INT64_MAX:
            message.int_value = value
        elif 0 <= value <= _UINT64_MAX:
            message.uint_value = value
        else:
            return None
    elif isinstance(value, float):
        message.double_value = value
    elif isinstance(value, str):
        message.string_value = value
    elif isinstance(value, enum.Enum):
        return _python_to_scalar(value.value)
    else:
        return None
    return message


def _require_scalar(value: pb2.ScalarValue, label: str):
    if value.WhichOneof("kind") is None:
        raise ValueError(f"{label} has no scalar value")
    return _scalar_to_python(value)


def _known_names(descriptor) -> set[str]:
    """Pydantic keys this message owns, including flattened base fields.

    ``*_raw`` companions are not keys. ``OcrLang`` is the ``lang`` key.
    """
    names: set[str] = set()
    for field in descriptor.fields:
        if field.name == "base":
            names.update(_known_names(field.message_type))
            continue
        if field.name.endswith("_raw"):
            continue
        if (
            field.type == FieldDescriptor.TYPE_MESSAGE
            and field.message_type.name == "OcrLang"
        ):
            names.add("lang")
            continue
        names.add(field.name)
    return names


def _known_field_names(message) -> set[str]:
    return _known_names(message.DESCRIPTOR)


def _base_to_dict(base) -> dict:
    data: dict = {}
    mode = _closed_literal(base, "mode", "mode_raw", "OcrOptions.mode")
    has_force = base.HasField("force_full_page_ocr")
    if mode is not None and has_force:
        raise ValueError(
            "OcrOptions.mode and force_full_page_ocr are both set. "
            "force_full_page_ocr is the deprecated alias of mode FULL_PAGE."
        )
    if mode is not None:
        data["mode"] = mode
    if has_force:
        data["force_full_page_ocr"] = base.force_full_page_ocr
    if base.HasField("lang"):
        data["lang"] = list(base.lang.values)
    if base.HasField("scale"):
        data["scale"] = base.scale
    if base.HasField("replace_broken_text_layer"):
        data["replace_broken_text_layer"] = base.replace_broken_text_layer
    return data


def _map_field_to_python(message, field: FieldDescriptor) -> dict:
    raw = getattr(message, field.name)
    value_field = field.message_type.fields_by_name["value"]
    if (
        value_field.type == FieldDescriptor.TYPE_MESSAGE
        and value_field.message_type.name == "ScalarValue"
    ):
        return {
            key: _require_scalar(item, f"{field.name}[{key!r}]")
            for key, item in raw.items()
        }
    return dict(raw)


def _channel_args_to_python(message) -> list[tuple[str, object]]:
    args = []
    for index, arg in enumerate(message.grpc_channel_args):
        if not arg.HasField("key"):
            raise ValueError(f"grpc_channel_args[{index}] key is unset")
        args.append(
            (arg.key, _require_scalar(arg.value, f"grpc_channel_args[{index}].value"))
        )
    return args


def _copy_set_field(message, field: FieldDescriptor, data: dict) -> None:
    name = field.name
    if name == "base" or name.endswith("_raw"):
        return
    if field.type == FieldDescriptor.TYPE_ENUM:
        value = _closed_literal(message, name, f"{name}_raw", name)
        if value is not None:
            data[name] = value
        return
    if (
        field.type == FieldDescriptor.TYPE_MESSAGE
        and field.message_type.GetOptions().map_entry
    ):
        if len(getattr(message, name)):
            data[name] = _map_field_to_python(message, field)
        return
    if (
        field.type == FieldDescriptor.TYPE_MESSAGE
        and field.message_type.name == "KserveGrpcChannelArg"
    ):
        if len(message.grpc_channel_args):
            data["grpc_channel_args"] = _channel_args_to_python(message)
        return
    if field.is_repeated:
        values = list(getattr(message, name))
        if values:
            data[name] = values
        return
    if message.HasField(name):
        data[name] = getattr(message, name)


def _arm_to_dict(message, arm: str) -> dict:
    data = {"kind": _ARM_KIND[arm]}
    if message.HasField("base"):
        data.update(_base_to_dict(message.base))
    for field in message.DESCRIPTOR.fields:
        _copy_set_field(message, field, data)
    return data


def _merge_custom(typed: dict, custom: dict, known: set[str]) -> None:
    conflicts = []
    for key, value in custom.items():
        if key == "kind":
            if value != typed["kind"]:
                conflicts.append("kind")
            continue
        if key in known:
            conflicts.append(key)
            continue
        typed[key] = value
    if conflicts:
        names = ", ".join(sorted(set(conflicts)))
        raise ValueError(
            "ocr_custom_config conflicts with typed OCR options on "
            f"{names}. The typed oneof owns those fields. The map is only "
            "for keys that message does not define."
        )


def apply_typed_ocr_options(
    proto_options,
    data: dict,
    custom: dict,
    *,
    ocr_engine: Optional[str],
    ocr_lang: list[str],
    ocr_preset: Optional[str],
) -> bool:
    """Write ``ocr_custom_config`` from the oneof. Return False when it is unset."""
    arm = proto_options.WhichOneof("ocr_options")
    if not arm:
        return False
    message = getattr(proto_options, arm)
    typed = _arm_to_dict(message, arm)
    _merge_custom(typed, custom, _known_field_names(message))
    if ocr_lang:
        if "lang" in typed:
            raise ValueError("ocr_lang conflicts with typed OCR options field lang")
        typed["lang"] = list(ocr_lang)
    if ocr_engine is not None and ocr_engine != typed["kind"]:
        raise ValueError(
            f"ocr_engine {ocr_engine!r} conflicts with typed OCR kind {typed['kind']!r}"
        )
    if ocr_preset not in (None, "", "auto"):
        raise ValueError(f"ocr_preset {ocr_preset!r} conflicts with typed OCR options")
    data["ocr_custom_config"] = typed
    return True


def _locate(message, key: str):
    fields = message.DESCRIPTOR.fields_by_name
    if key in fields:
        return message, fields[key]
    base = fields.get("base")
    if base is not None and key in base.message_type.fields_by_name:
        return message.base, base.message_type.fields_by_name[key]
    raise KeyError(key)


def _assign_enum(parent, name: str, value) -> None:
    text = value.value if isinstance(value, enum.Enum) else str(value)
    tag = _ENUM_TO_TAG[name].get(text)
    if tag is None:
        setattr(parent, f"{name}_raw", text)
        return
    setattr(parent, name, tag)


def _assign_map(parent, field: FieldDescriptor, value: dict) -> None:
    if not isinstance(value, dict):
        raise ValueError(f"{field.name} must be a dict")
    target = getattr(parent, field.name)
    target.clear()
    value_field = field.message_type.fields_by_name["value"]
    scalar_values = (
        value_field.type == FieldDescriptor.TYPE_MESSAGE
        and value_field.message_type.name == "ScalarValue"
    )
    for key, item in value.items():
        if scalar_values:
            scalar = _python_to_scalar(item)
            if scalar is None:
                raise ValueError(f"{field.name}[{key!r}] is not a scalar")
            target[key].CopyFrom(scalar)
        else:
            if not isinstance(item, str):
                raise ValueError(f"{field.name}[{key!r}] must be a string")
            target[key] = item


def _assign_channel_args(parent, value) -> None:
    if not isinstance(value, (list, tuple)):
        raise ValueError("grpc_channel_args must be a list of pairs")
    del parent.grpc_channel_args[:]
    for index, item in enumerate(value):
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            raise ValueError(f"grpc_channel_args[{index}] must be a (key, value) pair")
        key, raw = item
        if not isinstance(key, str):
            raise ValueError(f"grpc_channel_args[{index}] key must be a string")
        scalar = _python_to_scalar(raw)
        if scalar is None:
            raise ValueError(f"grpc_channel_args[{index}] value is not a scalar")
        arg = parent.grpc_channel_args.add()
        arg.key = key
        arg.value.CopyFrom(scalar)


def _assign_known(message, key: str, value) -> None:
    if value is None:
        return
    parent, field = _locate(message, key)
    if (
        field.type == FieldDescriptor.TYPE_MESSAGE
        and field.message_type.name == "OcrLang"
    ):
        if not isinstance(value, (list, tuple)):
            raise ValueError("lang must be a list of strings")
        parent.lang.SetInParent()
        del parent.lang.values[:]
        parent.lang.values.extend(value)
        return
    if field.type == FieldDescriptor.TYPE_ENUM:
        _assign_enum(parent, field.name, value)
        return
    if (
        field.type == FieldDescriptor.TYPE_MESSAGE
        and field.message_type.GetOptions().map_entry
    ):
        _assign_map(parent, field, value)
        return
    if (
        field.type == FieldDescriptor.TYPE_MESSAGE
        and field.message_type.name == "KserveGrpcChannelArg"
    ):
        _assign_channel_args(parent, value)
        return
    setattr(parent, field.name, value)


def _fill_scalar_map(message, values: dict) -> None:
    for key, value in values.items():
        if value is None:
            continue
        scalar = _python_to_scalar(value)
        if scalar is None:
            raise ValueError(f"ocr_custom_config[{key!r}] is not a scalar")
        message.ocr_custom_config[key].CopyFrom(scalar)


def ocr_config_to_proto(config: dict) -> pb2.ConvertDocumentOptions:
    """Inverse of the typed dict written into ``ocr_custom_config``.

    A kind with no message stays entirely in ``ocr_custom_config``. Known keys
    of a known kind go on the oneof. Other keys stay on the map.
    """
    kind = config.get("kind")
    if not isinstance(kind, str) or not kind:
        raise ValueError("ocr config requires a non-empty string kind")
    out = pb2.ConvertDocumentOptions()
    arm = _KIND_TO_ARM.get(kind)
    if arm is None:
        _fill_scalar_map(out, config)
        return out
    target = getattr(out, arm)
    target.SetInParent()
    known = _known_field_names(target)
    custom: dict = {}
    for key, value in config.items():
        if key == "kind" or value is None:
            continue
        if key in known:
            _assign_known(target, key, value)
        else:
            custom[key] = value
    if custom:
        _fill_scalar_map(out, custom)
    return out


def ocr_model_to_proto(model) -> pb2.ConvertDocumentOptions:
    """Copy fields the caller set on an ``OcrOptions`` instance.

    Defaults that Pydantic filled are left unset. ``None`` stays unset.
    Explicit false is set. A scalar field the proto does not know yet is kept
    on ``ocr_custom_config`` so it is not dropped. A non-scalar unknown field
    is an error.
    """
    kind = model.kind
    arm = _KIND_TO_ARM.get(kind)
    if arm is None:
        raise ValueError(f"no typed OCR message for kind {kind!r}")
    out = pb2.ConvertDocumentOptions()
    target = getattr(out, arm)
    target.SetInParent()
    known = _known_field_names(target)
    extra: dict = {}
    for key in model.model_fields_set:
        value = getattr(model, key)
        if value is None:
            continue
        if key in known:
            _assign_known(target, key, value)
            continue
        scalar = _python_to_scalar(value)
        if scalar is None:
            raise ValueError(
                f"{type(model).__name__}.{key} is not on the OCR proto message"
            )
        extra[key] = value
    if extra:
        _fill_scalar_map(out, extra)
    return out
