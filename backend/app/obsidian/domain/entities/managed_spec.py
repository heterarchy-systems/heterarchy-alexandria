"""Deterministic managed-spec request and envelope hashes."""

from __future__ import annotations

import hashlib

from app.obsidian.domain.contracts.managed_spec_contracts import (
    ManagedSpecCompleteRequest,
    ManagedSpecEnvelope,
    ManagedSpecExecutionContext,
    ManagedSpecIdentity,
)
from app.shared.serialization.orjson_codec import dumps_canonical_json
from app.shared.types.extra_types import JSONObject


def managed_spec_prepare_request_hash(
    *,
    spec_identity: ManagedSpecIdentity,
    logical_date: str,
    idempotency_key: str,
    execution_context: ManagedSpecExecutionContext,
) -> str:
    """Hash the complete prepare input for durable same-key fencing."""
    payload: JSONObject = {
        "spec_note_id": spec_identity.note_id,
        "logical_date": logical_date,
        "idempotency_key": idempotency_key,
        "execution_context": {
            "project": execution_context.project,
            "workflow": execution_context.workflow,
            "entity": execution_context.entity,
            "edition": execution_context.edition,
            "expected_policy_note_id": execution_context.expected_policy_note_id,
        },
    }
    return hashlib.sha256(dumps_canonical_json(payload)).hexdigest()


def managed_spec_envelope_hash(envelope: ManagedSpecEnvelope) -> str:
    """Hash the pinned source identity and trust-boundary fields."""
    payload: JSONObject = {
        "idempotency_key": envelope.idempotency_key,
        "spec_note_id": envelope.spec_identity.note_id,
        "logical_identity": {
            "project": envelope.logical_identity.project,
            "report": envelope.logical_identity.report,
            "date": envelope.logical_identity.date,
            "entity": envelope.logical_identity.entity,
            "edition": envelope.logical_identity.edition,
        },
        "policy_note_id": envelope.policy_note_id,
        "policy_version": envelope.policy_version,
        "policy_content_hash": envelope.policy_content_hash,
        "policy_body": envelope.policy_body,
        "spec_version": envelope.spec_version,
        "spec_content_hash": envelope.spec_content_hash,
        "spec_body": envelope.spec_body,
        "allowed_workflow": envelope.allowed_workflow,
        "reference_only": envelope.reference_only,
        "may_expand_permissions": envelope.may_expand_permissions,
        "may_start_unrelated_work": envelope.may_start_unrelated_work,
    }
    return hashlib.sha256(dumps_canonical_json(payload)).hexdigest()


def managed_spec_completion_request_hash(
    *,
    request: ManagedSpecCompleteRequest,
) -> str:
    """Hash explicit completion fields so retries cannot change the output."""
    payload: JSONObject = {
        "idempotency_key": request.idempotency_key,
        "prepared_envelope_hash": request.prepared_envelope_hash,
        "output_title": request.output_title,
        "output_body": request.output_body,
        "expected_output_content_hash": request.expected_output_content_hash,
    }
    return hashlib.sha256(dumps_canonical_json(payload)).hexdigest()
