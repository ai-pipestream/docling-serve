"""Typed OCR oneof: each engine, unset versus false, and the custom-config fallback."""

import pytest

from docling.datamodel.pipeline_options import (
    EasyOcrOptions,
    KserveV2OcrOptions,
    NemotronOcrOptions,
    OcrAutoOptions,
    OcrMacOptions,
    OcrOptions,
    RapidOcrOptions,
)

from docling_serve.grpc.gen.ai.docling.serve.v1 import docling_serve_types_pb2 as pb2
from docling_serve.grpc.mapping import to_convert_options
from docling_serve.grpc.ocr_mapping import (
    ocr_config_to_proto,
    ocr_kind_to_arm,
    ocr_model_to_proto,
)

pytestmark = pytest.mark.unit


def _scalar_map(**kwargs):
    out = {}
    for key, value in kwargs.items():
        msg = pb2.ScalarValue()
        if isinstance(value, bool):
            msg.bool_value = value
        elif isinstance(value, int):
            msg.int_value = value
        elif isinstance(value, float):
            msg.double_value = value
        else:
            msg.string_value = str(value)
        out[key] = msg
    return out


def _options(**kwargs):
    return pb2.ConvertDocumentOptions(**kwargs)


def test_every_ocr_subclass_has_a_message_and_kind():
    pending = list(OcrOptions.__subclasses__())
    found = []
    while pending:
        cls = pending.pop()
        pending.extend(cls.__subclasses__())
        found.append(cls)
    names = {cls.__name__ for cls in found}
    assert names == {
        "OcrAutoOptions",
        "EasyOcrOptions",
        "TesseractCliOcrOptions",
        "TesseractOcrOptions",
        "RapidOcrOptions",
        "OcrMacOptions",
        "NemotronOcrOptions",
        "KserveV2OcrOptions",
    }
    missing_messages = [
        name for name in names if name not in pb2.DESCRIPTOR.message_types_by_name
    ]
    assert missing_messages == []
    kinds = {cls.kind for cls in found}
    assert kinds == set(ocr_kind_to_arm())


def test_easyocr_unset_gpu_is_not_false_and_explicit_false_is_false():
    unset = to_convert_options(_options(easyocr=pb2.EasyOcrOptions()))
    assert unset.ocr_custom_config == {"kind": "easyocr"}
    assert "use_gpu" not in unset.ocr_custom_config
    assert "download_enabled" not in unset.ocr_custom_config
    assert "replace_broken_text_layer" not in unset.ocr_custom_config

    explicit = to_convert_options(
        _options(
            easyocr=pb2.EasyOcrOptions(
                use_gpu=False,
                download_enabled=False,
                base=pb2.OcrOptionsBase(replace_broken_text_layer=False),
            )
        )
    )
    assert explicit.ocr_custom_config["use_gpu"] is False
    assert explicit.ocr_custom_config["download_enabled"] is False
    assert explicit.ocr_custom_config["replace_broken_text_layer"] is False
    assert "confidence_threshold" not in explicit.ocr_custom_config

    model = EasyOcrOptions.model_validate(
        {
            "use_gpu": False,
            "download_enabled": False,
            "replace_broken_text_layer": False,
        }
    )
    proto = ocr_model_to_proto(model)
    assert proto.WhichOneof("ocr_options") == "easyocr"
    assert proto.easyocr.HasField("use_gpu") and proto.easyocr.use_gpu is False
    assert proto.easyocr.download_enabled is False
    assert proto.easyocr.base.replace_broken_text_layer is False
    assert not proto.easyocr.HasField("confidence_threshold")
    assert not proto.easyocr.base.HasField("scale")
    assert not proto.easyocr.base.HasField("lang")


def test_tesseract_bindings_psm_zero_is_distinct_from_unset():
    unset = to_convert_options(_options(tesseract=pb2.TesseractOcrOptions()))
    assert unset.ocr_custom_config == {"kind": "tesserocr"}
    assert "psm" not in unset.ocr_custom_config
    assert "path" not in unset.ocr_custom_config

    explicit = to_convert_options(
        _options(
            tesseract=pb2.TesseractOcrOptions(
                psm=0,
                base=pb2.OcrOptionsBase(replace_broken_text_layer=False),
            )
        )
    )
    assert explicit.ocr_custom_config["kind"] == "tesserocr"
    assert explicit.ocr_custom_config["psm"] == 0
    assert explicit.ocr_custom_config["replace_broken_text_layer"] is False

    back = ocr_config_to_proto(explicit.ocr_custom_config)
    assert back.WhichOneof("ocr_options") == "tesseract"
    assert back.tesseract.HasField("psm") and back.tesseract.psm == 0
    assert back.tesseract.base.replace_broken_text_layer is False
    assert not back.tesseract.HasField("path")


def test_tesseract_cli_lang_empty_is_distinct_from_unset():
    unset = to_convert_options(_options(tesseract_cli=pb2.TesseractCliOcrOptions()))
    assert unset.ocr_custom_config == {"kind": "tesseract"}
    assert "lang" not in unset.ocr_custom_config

    empty_lang = pb2.TesseractCliOcrOptions()
    empty_lang.base.lang.SetInParent()
    empty = to_convert_options(_options(tesseract_cli=empty_lang))
    assert empty.ocr_custom_config["lang"] == []
    assert empty.ocr_custom_config["kind"] == "tesseract"

    filled = to_convert_options(
        _options(
            tesseract_cli=pb2.TesseractCliOcrOptions(
                tesseract_cmd="/usr/bin/tesseract",
                psm=0,
                base=pb2.OcrOptionsBase(
                    lang=pb2.OcrLang(values=["deu", "eng"]),
                    replace_broken_text_layer=True,
                ),
            )
        )
    )
    assert filled.ocr_custom_config["tesseract_cmd"] == "/usr/bin/tesseract"
    assert filled.ocr_custom_config["psm"] == 0
    assert filled.ocr_custom_config["lang"] == ["deu", "eng"]
    assert filled.ocr_custom_config["replace_broken_text_layer"] is True
    assert "path" not in filled.ocr_custom_config


def test_rapidocr_orientation_and_tri_state_flags():
    unset = to_convert_options(_options(rapidocr=pb2.RapidOcrOptions()))
    assert unset.ocr_custom_config == {"kind": "rapidocr"}
    for key in (
        "detect_orientation",
        "use_det",
        "use_cls",
        "use_rec",
        "print_verbose",
        "backend",
        "model_size",
    ):
        assert key not in unset.ocr_custom_config

    explicit = to_convert_options(
        _options(
            rapidocr=pb2.RapidOcrOptions(
                detect_orientation=False,
                use_det=False,
                use_cls=True,
                print_verbose=False,
                backend=pb2.RAPID_OCR_BACKEND_TORCH,
                text_score=0.1,
            )
        )
    )
    cfg = explicit.ocr_custom_config
    assert cfg["detect_orientation"] is False
    assert cfg["use_det"] is False
    assert cfg["use_cls"] is True
    assert cfg["print_verbose"] is False
    assert cfg["backend"] == "torch"
    assert cfg["text_score"] == pytest.approx(0.1)
    assert "use_rec" not in cfg
    assert "model_size" not in cfg

    back = ocr_config_to_proto(cfg)
    assert back.rapidocr.detect_orientation is False
    assert back.rapidocr.HasField("use_det") and back.rapidocr.use_det is False
    assert not back.rapidocr.HasField("use_rec")
    assert back.rapidocr.backend == pb2.RAPID_OCR_BACKEND_TORCH
    assert not back.rapidocr.HasField("backend_raw")

    model = RapidOcrOptions.model_validate(
        {"detect_orientation": False, "use_det": False, "backend": "openvino"}
    )
    from_model = ocr_model_to_proto(model)
    assert from_model.rapidocr.detect_orientation is False
    assert from_model.rapidocr.use_det is False
    assert from_model.rapidocr.backend == pb2.RAPID_OCR_BACKEND_OPENVINO
    assert not from_model.rapidocr.HasField("print_verbose")
    assert not from_model.rapidocr.base.HasField("scale")


def test_rapidocr_unknown_backend_uses_raw_and_disagreement_errors():
    message = pb2.RapidOcrOptions()
    message.backend_raw = "tensorrt"
    mapped = to_convert_options(_options(rapidocr=message))
    assert mapped.ocr_custom_config["backend"] == "tensorrt"

    conflict = pb2.RapidOcrOptions(
        backend=pb2.RAPID_OCR_BACKEND_ONNXRUNTIME,
        backend_raw="torch",
    )
    with pytest.raises(ValueError, match="disagree"):
        to_convert_options(_options(rapidocr=conflict))


def test_ocrmac_strings_and_unset_bool():
    unset = to_convert_options(_options(ocrmac=pb2.OcrMacOptions()))
    assert unset.ocr_custom_config == {"kind": "ocrmac"}
    explicit = to_convert_options(
        _options(
            ocrmac=pb2.OcrMacOptions(
                recognition="fast",
                framework="vision",
                base=pb2.OcrOptionsBase(replace_broken_text_layer=False),
            )
        )
    )
    assert explicit.ocr_custom_config["recognition"] == "fast"
    assert explicit.ocr_custom_config["framework"] == "vision"
    assert explicit.ocr_custom_config["replace_broken_text_layer"] is False
    model = OcrMacOptions.model_validate(
        {"recognition": "fast", "replace_broken_text_layer": False}
    )
    proto = ocr_model_to_proto(model)
    assert proto.ocrmac.recognition == "fast"
    assert not proto.ocrmac.HasField("framework")
    assert proto.ocrmac.base.replace_broken_text_layer is False


def test_nemotron_merge_level_and_batch_size():
    unset = to_convert_options(_options(nemotron_ocr=pb2.NemotronOcrOptions()))
    assert unset.ocr_custom_config == {"kind": "nemotron-ocr"}
    assert "merge_level" not in unset.ocr_custom_config
    assert "batch_size" not in unset.ocr_custom_config

    explicit = to_convert_options(
        _options(
            nemotron_ocr=pb2.NemotronOcrOptions(
                merge_level=pb2.NEMOTRON_OCR_MERGE_LEVEL_WORD,
                batch_size=1,
                base=pb2.OcrOptionsBase(replace_broken_text_layer=False),
            )
        )
    )
    assert explicit.ocr_custom_config["merge_level"] == "word"
    assert explicit.ocr_custom_config["batch_size"] == 1
    assert explicit.ocr_custom_config["replace_broken_text_layer"] is False

    model = NemotronOcrOptions.model_validate(
        {
            "merge_level": "paragraph",
            "batch_size": 4,
            "replace_broken_text_layer": False,
        }
    )
    proto = ocr_model_to_proto(model)
    assert proto.nemotron_ocr.merge_level == pb2.NEMOTRON_OCR_MERGE_LEVEL_PARAGRAPH
    assert proto.nemotron_ocr.batch_size == 4
    assert proto.nemotron_ocr.base.replace_broken_text_layer is False


def test_kserve_unset_tls_is_not_false():
    unset = to_convert_options(_options(kserve_v2_ocr=pb2.KserveV2OcrOptions()))
    assert unset.ocr_custom_config == {"kind": "kserve_v2_ocr"}
    assert "grpc_use_tls" not in unset.ocr_custom_config
    assert "use_binary_data" not in unset.ocr_custom_config
    assert "url" not in unset.ocr_custom_config

    explicit = to_convert_options(
        _options(
            kserve_v2_ocr=pb2.KserveV2OcrOptions(
                url="localhost:8001",
                grpc_use_tls=False,
                use_binary_data=False,
                transport=pb2.KSERVE_V2_TRANSPORT_HTTP,
                timeout=1.5,
                headers={"authorization": "Bearer t"},
                grpc_channel_args=[
                    pb2.KserveGrpcChannelArg(
                        key="grpc.lb_policy_name",
                        value=pb2.ScalarValue(string_value="round_robin"),
                    )
                ],
                request_parameters={"keep": pb2.ScalarValue(bool_value=False)},
            )
        )
    )
    cfg = explicit.ocr_custom_config
    assert cfg["url"] == "localhost:8001"
    assert cfg["grpc_use_tls"] is False
    assert cfg["use_binary_data"] is False
    assert cfg["transport"] == "http"
    assert cfg["timeout"] == pytest.approx(1.5)
    assert cfg["headers"] == {"authorization": "Bearer t"}
    assert cfg["grpc_channel_args"] == [("grpc.lb_policy_name", "round_robin")]
    assert cfg["request_parameters"] == {"keep": False}

    model = KserveV2OcrOptions.model_validate(
        {"url": "localhost:8001", "grpc_use_tls": False, "transport": "grpc"}
    )
    proto = ocr_model_to_proto(model)
    assert proto.kserve_v2_ocr.url == "localhost:8001"
    assert proto.kserve_v2_ocr.grpc_use_tls is False
    assert proto.kserve_v2_ocr.transport == pb2.KSERVE_V2_TRANSPORT_GRPC
    assert not proto.kserve_v2_ocr.HasField("use_binary_data")


def test_kserve_unknown_transport_uses_raw():
    model = KserveV2OcrOptions.model_construct(url="localhost:8001", transport="quic")
    proto = ocr_model_to_proto(model)
    assert not proto.kserve_v2_ocr.HasField("transport")
    assert proto.kserve_v2_ocr.transport_raw == "quic"
    mapped = to_convert_options(proto)
    assert mapped.ocr_custom_config["transport"] == "quic"


def test_auto_mode_raw_and_force_alias():
    unset = to_convert_options(_options(ocr_auto=pb2.OcrAutoOptions()))
    assert unset.ocr_custom_config == {"kind": "auto"}

    forced = pb2.OcrAutoOptions(base=pb2.OcrOptionsBase(force_full_page_ocr=False))
    mapped = to_convert_options(_options(ocr_auto=forced))
    assert mapped.ocr_custom_config["force_full_page_ocr"] is False
    assert "mode" not in mapped.ocr_custom_config

    full = pb2.OcrAutoOptions(base=pb2.OcrOptionsBase(force_full_page_ocr=True))
    assert (
        to_convert_options(_options(ocr_auto=full)).ocr_custom_config[
            "force_full_page_ocr"
        ]
        is True
    )

    both = pb2.OcrAutoOptions(
        base=pb2.OcrOptionsBase(
            mode=pb2.OCR_MODE_FULL_PAGE,
            force_full_page_ocr=True,
        )
    )
    with pytest.raises(ValueError, match="force_full_page_ocr"):
        to_convert_options(_options(ocr_auto=both))

    raw = pb2.OcrAutoOptions()
    raw.base.mode_raw = "regions_v2"
    assert to_convert_options(_options(ocr_auto=raw)).ocr_custom_config["mode"] == (
        "regions_v2"
    )

    model = OcrAutoOptions.model_validate({"mode": "layout_regions", "lang": []})
    proto = ocr_model_to_proto(model)
    assert proto.ocr_auto.base.mode == pb2.OCR_MODE_LAYOUT_REGIONS
    assert proto.ocr_auto.base.HasField("lang")
    assert list(proto.ocr_auto.base.lang.values) == []
    assert not proto.ocr_auto.base.HasField("force_full_page_ocr")


def test_typed_field_repeated_in_custom_config_is_an_error():
    with pytest.raises(ValueError, match="conflicts"):
        to_convert_options(
            _options(
                easyocr=pb2.EasyOcrOptions(use_gpu=True),
                ocr_custom_config=_scalar_map(use_gpu=False),
            )
        )


def test_untyped_custom_key_is_kept_and_typed_value_is_not_overridden():
    mapped = to_convert_options(
        _options(
            rapidocr=pb2.RapidOcrOptions(detect_orientation=False),
            ocr_custom_config=_scalar_map(future_flag=False),
        )
    )
    assert mapped.ocr_custom_config["detect_orientation"] is False
    assert mapped.ocr_custom_config["future_flag"] is False
    assert mapped.ocr_custom_config["kind"] == "rapidocr"

    back = ocr_config_to_proto(mapped.ocr_custom_config)
    assert back.rapidocr.detect_orientation is False
    assert back.ocr_custom_config["future_flag"].bool_value is False
    assert "detect_orientation" not in back.ocr_custom_config


def test_ocr_engine_and_preset_conflicts():
    with pytest.raises(ValueError, match="ocr_engine"):
        to_convert_options(
            _options(
                ocr_engine=pb2.OCR_ENGINE_EASYOCR,
                rapidocr=pb2.RapidOcrOptions(),
            )
        )
    matched = to_convert_options(
        _options(
            ocr_engine=pb2.OCR_ENGINE_EASYOCR,
            easyocr=pb2.EasyOcrOptions(use_gpu=False),
        )
    )
    assert matched.ocr_custom_config["kind"] == "easyocr"
    assert matched.ocr_custom_config["use_gpu"] is False
    assert "ocr_engine" not in matched.model_fields_set

    with pytest.raises(ValueError, match="ocr_preset"):
        to_convert_options(_options(ocr_preset="easyocr", easyocr=pb2.EasyOcrOptions()))


def test_ocr_lang_fills_unset_typed_lang_and_conflicts_when_both_set():
    filled = to_convert_options(
        _options(tesseract_cli=pb2.TesseractCliOcrOptions(), ocr_lang=["deu"])
    )
    assert filled.ocr_custom_config["lang"] == ["deu"]

    arm = pb2.TesseractCliOcrOptions()
    arm.base.lang.values.append("eng")
    with pytest.raises(ValueError, match="ocr_lang"):
        to_convert_options(_options(tesseract_cli=arm, ocr_lang=["deu"]))


def test_legacy_custom_config_without_oneof_is_unchanged():
    mapped = to_convert_options(
        _options(ocr_custom_config=_scalar_map(kind="easyocr", use_gpu=True))
    )
    assert mapped.ocr_custom_config == {"kind": "easyocr", "use_gpu": True}


def test_unknown_kind_stays_on_the_map():
    proto = ocr_config_to_proto({"kind": "plugin-ocr", "threshold": 0.2})
    assert proto.WhichOneof("ocr_options") is None
    assert proto.ocr_custom_config["kind"].string_value == "plugin-ocr"
    assert proto.ocr_custom_config["threshold"].double_value == pytest.approx(0.2)


def test_nested_rapidocr_param_is_rejected():
    with pytest.raises(ValueError, match="not a scalar"):
        ocr_config_to_proto(
            {"kind": "rapidocr", "rapidocr_params": {"det": {"limit": 1}}}
        )


def test_ocr_mode_full_page_round_trip():
    mapped = to_convert_options(
        _options(
            ocr_auto=pb2.OcrAutoOptions(
                base=pb2.OcrOptionsBase(mode=pb2.OCR_MODE_LAYOUT_REGIONS, scale=2.0)
            )
        )
    )
    assert mapped.ocr_custom_config["mode"] == "layout_regions"
    assert mapped.ocr_custom_config["scale"] == pytest.approx(2.0)
    back = ocr_config_to_proto(mapped.ocr_custom_config)
    assert back.ocr_auto.base.mode == pb2.OCR_MODE_LAYOUT_REGIONS
    assert back.ocr_auto.base.scale == pytest.approx(2.0)
    assert not back.ocr_auto.base.HasField("replace_broken_text_layer")
