"""OcrOptionsBase and every OCR arm: proto -> pydantic dict -> proto equality.

Complements tests/test_grpc_ocr_options.py with an exhaustive base-field matrix
and a full-arm round-trip that keeps typed equality (no JSON).
"""

from __future__ import annotations

import pytest

from docling_serve.grpc.gen.ai.docling.serve.v1 import docling_serve_types_pb2 as pb2
from docling_serve.grpc.mapping import to_convert_options
from docling_serve.grpc.ocr_mapping import ocr_config_to_proto, ocr_model_to_proto

pytestmark = pytest.mark.unit


def _base(**kwargs) -> pb2.OcrOptionsBase:
    return pb2.OcrOptionsBase(**kwargs)


def test_ocr_options_base_every_field_round_trips_through_auto():
    base = _base(
        mode=pb2.OCR_MODE_FULL_PAGE,
        scale=1.5,
        replace_broken_text_layer=True,
    )
    base.lang.values.extend(["en", "de"])
    proto = pb2.ConvertDocumentOptions(ocr_auto=pb2.OcrAutoOptions(base=base))
    mapped = to_convert_options(proto)
    cfg = mapped.ocr_custom_config
    assert cfg["kind"] == "auto"
    assert cfg["mode"] == "full_page"
    assert cfg["lang"] == ["en", "de"]
    assert cfg["scale"] == pytest.approx(1.5)
    assert cfg["replace_broken_text_layer"] is True

    back = ocr_config_to_proto(cfg)
    assert back.WhichOneof("ocr_options") == "ocr_auto"
    assert back.ocr_auto.base.mode == pb2.OCR_MODE_FULL_PAGE
    assert list(back.ocr_auto.base.lang.values) == ["en", "de"]
    assert back.ocr_auto.base.scale == pytest.approx(1.5)
    assert back.ocr_auto.base.replace_broken_text_layer is True


def test_ocr_options_base_unset_stays_omitted():
    proto = pb2.ConvertDocumentOptions(ocr_auto=pb2.OcrAutoOptions())
    mapped = to_convert_options(proto)
    cfg = mapped.ocr_custom_config
    assert cfg == {"kind": "auto"}
    for key in ("mode", "lang", "scale", "replace_broken_text_layer", "force_full_page_ocr"):
        assert key not in cfg


def test_mode_raw_unknown_round_trips():
    base = _base(mode_raw="future_mode")
    proto = pb2.ConvertDocumentOptions(ocr_auto=pb2.OcrAutoOptions(base=base))
    mapped = to_convert_options(proto)
    assert mapped.ocr_custom_config["mode"] == "future_mode"
    back = ocr_config_to_proto(mapped.ocr_custom_config)
    assert back.ocr_auto.base.mode_raw == "future_mode"
    assert back.ocr_auto.base.mode == pb2.OCR_MODE_UNSPECIFIED


@pytest.mark.parametrize(
    "arm,builder",
    [
        ("ocr_auto", lambda: pb2.ConvertDocumentOptions(ocr_auto=pb2.OcrAutoOptions())),
        ("easyocr", lambda: pb2.ConvertDocumentOptions(easyocr=pb2.EasyOcrOptions())),
        ("tesseract", lambda: pb2.ConvertDocumentOptions(tesseract=pb2.TesseractOcrOptions())),
        (
            "tesseract_cli",
            lambda: pb2.ConvertDocumentOptions(tesseract_cli=pb2.TesseractCliOcrOptions()),
        ),
        ("rapidocr", lambda: pb2.ConvertDocumentOptions(rapidocr=pb2.RapidOcrOptions())),
        ("ocrmac", lambda: pb2.ConvertDocumentOptions(ocrmac=pb2.OcrMacOptions())),
        (
            "nemotron_ocr",
            lambda: pb2.ConvertDocumentOptions(nemotron_ocr=pb2.NemotronOcrOptions()),
        ),
        (
            "kserve_v2_ocr",
            lambda: pb2.ConvertDocumentOptions(kserve_v2_ocr=pb2.KserveV2OcrOptions()),
        ),
    ],
)
def test_every_ocr_arm_empty_message_maps_and_round_trips(arm, builder):
    proto = builder()
    assert proto.WhichOneof("ocr_options") == arm
    mapped = to_convert_options(proto)
    assert "kind" in mapped.ocr_custom_config
    back = ocr_config_to_proto(mapped.ocr_custom_config)
    assert back.WhichOneof("ocr_options") == arm


def test_duplicate_typed_key_in_custom_config_is_error():
    options = pb2.ConvertDocumentOptions(
        rapidocr=pb2.RapidOcrOptions(
            base=_base(replace_broken_text_layer=True),
        ),
        ocr_custom_config={
            "replace_broken_text_layer": pb2.ScalarValue(bool_value=False),
        },
    )
    with pytest.raises(ValueError, match="replace_broken_text_layer"):
        to_convert_options(options)


def test_rapidocr_full_arm_round_trip_typed_equality():
    arm = pb2.RapidOcrOptions(
        base=_base(mode=pb2.OCR_MODE_DEFAULT, scale=2.0, replace_broken_text_layer=False),
        backend=pb2.RAPID_OCR_BACKEND_ONNXRUNTIME,
        model_size=pb2.RAPID_OCR_MODEL_SIZE_SMALL,
        text_score=0.7,
        use_det=True,
        use_cls=False,
        detect_orientation=True,
        use_rec=True,
        print_verbose=False,
    )
    arm.base.lang.values.append("en")
    proto = pb2.ConvertDocumentOptions(rapidocr=arm)
    mapped = to_convert_options(proto)
    back = ocr_config_to_proto(mapped.ocr_custom_config)
    assert back.WhichOneof("ocr_options") == "rapidocr"
    assert back.rapidocr.backend == pb2.RAPID_OCR_BACKEND_ONNXRUNTIME
    assert back.rapidocr.model_size == pb2.RAPID_OCR_MODEL_SIZE_SMALL
    assert back.rapidocr.text_score == pytest.approx(0.7)
    assert back.rapidocr.use_det is True
    assert back.rapidocr.use_cls is False
    assert back.rapidocr.detect_orientation is True
    assert back.rapidocr.HasField("use_rec") and back.rapidocr.use_rec is True
    assert back.rapidocr.base.replace_broken_text_layer is False
    assert list(back.rapidocr.base.lang.values) == ["en"]


def test_ocr_model_to_proto_matches_arm_for_each_installed_subclass():
    from docling.datamodel.pipeline_options import KserveV2OcrOptions, OcrOptions

    pending = list(OcrOptions.__subclasses__())
    seen = []
    while pending:
        cls = pending.pop()
        pending.extend(cls.__subclasses__())
        seen.append(cls)
    for cls in seen:
        if cls is KserveV2OcrOptions:
            model = cls(url="http://127.0.0.1:8080")
        else:
            model = cls()
        proto = ocr_model_to_proto(model)
        assert proto.WhichOneof("ocr_options") is not None, cls.__name__
