"""Bridge between the shared service policy and gRPC requests.

The REST layer enforces ``docling_serve.policy`` on Pydantic request models.
gRPC builds sources/options/target separately (it never constructs a
``ConvertSourcesRequest``), so this module applies the same rules to those
parts. The option-, target-kind, and source/target pairing validators are
reused from ``policy.py``. ``policy.py`` remains the source of truth — when
its rules change, this bridge must follow.
"""

from __future__ import annotations

from typing import Optional

from fastapi import HTTPException

from docling.datamodel.service.options import ConvertDocumentsOptions
from docling.datamodel.service.targets import PresignedUrlTarget

from docling_serve.policy import (
    ServicePolicy,
    _INLINE_SOURCE_KINDS,
    normalize_convert_options,
    validate_convert_options,
    validate_source_kinds,
    validate_source_target_pairing,
    validate_target_kind,
)


def normalize_options(
    options: ConvertDocumentsOptions, policy: ServicePolicy
) -> ConvertDocumentsOptions:
    """Apply policy defaults (e.g. document_timeout) like the REST layer does."""
    return normalize_convert_options(options, policy)


def validate_request(
    sources: list,
    options: ConvertDocumentsOptions,
    target,
    policy: ServicePolicy,
    *,
    chunk: bool = False,
) -> Optional[str]:
    """Validate a gRPC request against the service policy.

    Returns an error detail string when the request violates policy,
    or None when it is allowed.
    """
    try:
        validate_convert_options(options, policy)
        validate_target_kind(target.kind, policy)
    except HTTPException as exc:
        return str(exc.detail)

    if len(sources) > policy.max_sources_per_request:
        return (
            f"Too many sources: {len(sources)} exceeds the "
            f"maximum of {policy.max_sources_per_request}."
        )

    try:
        # Match REST convert/chunk: inline file/http sources are always allowed;
        # allowed_source_types gates storage connectors (batch-oriented).
        validate_source_kinds(sources, policy, skip_kinds=_INLINE_SOURCE_KINDS)
    except HTTPException as exc:
        return str(exc.detail)

    if isinstance(target, PresignedUrlTarget):
        if chunk:
            return "presigned_url target is not supported for chunk endpoints."
        if not policy.artifact_storage_enabled:
            return (
                "Presigned URL target requires artifact storage to be configured "
                "and enabled on the server."
            )

    try:
        validate_source_target_pairing(sources, target, policy)
    except HTTPException as exc:
        return str(exc.detail)

    return None
