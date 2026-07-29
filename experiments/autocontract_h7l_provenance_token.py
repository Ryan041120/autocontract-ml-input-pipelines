"""H7L signed, worker-portable provenance tokens with atomic consumption."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import secrets
import sqlite3
import tempfile
import threading
import time
from dataclasses import asdict, dataclass, fields, replace
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey


SCHEMA = "autocontract.provenance/v1"


def canonical_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


@dataclass(frozen=True)
class SubjectClaim:
    role: str
    sample_key: str
    content_sha256: str


@dataclass(frozen=True)
class ProvenancePayload:
    schema: str
    key_id: str
    run_id: str
    replay_sample_id: str
    dataset_id: str
    dataset_revision: str
    split: str
    dataset_manifest_sha256: str
    epoch: int
    sampler_context_sha256: str
    subjects: tuple[SubjectClaim, ...]
    operator_path: str
    registration_sha256: str
    input_content_sha256: str
    nonce: str


@dataclass(frozen=True)
class ProvenanceExpectation:
    run_id: str
    replay_sample_id: str
    dataset_id: str
    dataset_revision: str
    split: str
    dataset_manifest_sha256: str
    epoch: int
    sampler_context_sha256: str
    subjects: tuple[SubjectClaim, ...]
    operator_path: str
    registration_sha256: str
    input_content_sha256: str


@dataclass(frozen=True)
class SignedProvenanceToken:
    payload: ProvenancePayload
    signature_b64: str
    token_sha256: str

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    @classmethod
    def from_json(cls, value: str) -> "SignedProvenanceToken":
        raw = json.loads(value)
        payload = dict(raw["payload"])
        payload["subjects"] = tuple(SubjectClaim(**item) for item in payload["subjects"])
        return cls(
            payload=ProvenancePayload(**payload),
            signature_b64=str(raw["signature_b64"]),
            token_sha256=str(raw["token_sha256"]),
        )


@dataclass(frozen=True)
class VerifiedProvenance:
    token_sha256: str
    payload_sha256: str
    consumer_id: str
    payload: ProvenancePayload


class ProvenanceRejected(RuntimeError):
    def __init__(self, reasons: tuple[str, ...]) -> None:
        super().__init__("provenance rejected: " + ",".join(reasons))
        self.reasons = reasons


def payload_bytes(payload: ProvenancePayload) -> bytes:
    return canonical_bytes(asdict(payload))


def token_digest(payload: ProvenancePayload, signature: bytes) -> str:
    return sha256_bytes(payload_bytes(payload) + b"." + signature)


def dataset_manifest_digest(records: dict[str, str]) -> str:
    """Bind ordered sample keys to their content digests."""
    return sha256_bytes(canonical_bytes({key: records[key] for key in sorted(records)}))


class SqliteReplayRegistry:
    """Durable cross-process exactly-once state transition for signed tokens."""

    def __init__(
        self,
        path: Path,
        *,
        reset: bool = False,
        persistent_connections: bool = False,
    ) -> None:
        self.path = Path(path)
        self._persistent_connections = persistent_connections
        self._local = threading.local()
        if reset and self.path.exists():
            self.path.unlink()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30.0, isolation_level=None)
        connection.execute("PRAGMA busy_timeout=30000")
        return connection

    def _acquire(self) -> tuple[sqlite3.Connection, bool]:
        if not self._persistent_connections:
            return self._connect(), True
        connection = getattr(self._local, "connection", None)
        if connection is None:
            connection = self._connect()
            self._local.connection = connection
        return connection, False

    def close(self) -> None:
        connection = getattr(self._local, "connection", None)
        if connection is not None:
            connection.close()
            del self._local.connection

    def _initialize(self) -> None:
        connection = self._connect()
        try:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS replay_tokens (
                    token_sha256 TEXT PRIMARY KEY,
                    payload_sha256 TEXT NOT NULL,
                    state TEXT NOT NULL CHECK(state IN ('issued', 'consumed', 'revoked')),
                    issued_ns INTEGER NOT NULL,
                    consumed_by TEXT,
                    consumed_ns INTEGER
                )
                """
            )
            connection.commit()
        finally:
            connection.close()

    def register(self, token: SignedProvenanceToken) -> None:
        digest = sha256_bytes(payload_bytes(token.payload))
        connection, owned = self._acquire()
        try:
            connection.execute(
                "INSERT INTO replay_tokens VALUES (?, ?, 'issued', ?, NULL, NULL)",
                (token.token_sha256, digest, time.time_ns()),
            )
            connection.commit()
        except sqlite3.IntegrityError as error:
            raise ProvenanceRejected(("token_already_registered",)) from error
        finally:
            if owned:
                connection.close()

    def revoke(self, token_sha256: str) -> None:
        connection, owned = self._acquire()
        try:
            cursor = connection.execute(
                "UPDATE replay_tokens SET state='revoked' WHERE token_sha256=? AND state='issued'",
                (token_sha256,),
            )
            if cursor.rowcount != 1:
                raise ProvenanceRejected(("token_not_revocable",))
            connection.commit()
        finally:
            if owned:
                connection.close()

    def consume(self, token_sha256: str, payload_sha256: str, consumer_id: str) -> None:
        connection, owned = self._acquire()
        try:
            connection.execute("BEGIN IMMEDIATE")
            record = connection.execute(
                "SELECT payload_sha256, state FROM replay_tokens WHERE token_sha256=?",
                (token_sha256,),
            ).fetchone()
            if record is None:
                raise ProvenanceRejected(("token_not_registered",))
            stored_payload, state = record
            if stored_payload != payload_sha256:
                raise ProvenanceRejected(("registry_payload_mismatch",))
            if state != "issued":
                raise ProvenanceRejected((f"token_{state}",))
            cursor = connection.execute(
                "UPDATE replay_tokens SET state='consumed', consumed_by=?, consumed_ns=? "
                "WHERE token_sha256=? AND state='issued'",
                (consumer_id, time.time_ns(), token_sha256),
            )
            if cursor.rowcount != 1:
                raise ProvenanceRejected(("token_consume_race_lost",))
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            if owned:
                connection.close()

    def state(self, token_sha256: str) -> str | None:
        connection, owned = self._acquire()
        try:
            record = connection.execute(
                "SELECT state FROM replay_tokens WHERE token_sha256=?", (token_sha256,),
            ).fetchone()
            return None if record is None else str(record[0])
        finally:
            if owned:
                connection.close()


class ProvenanceAuthority:
    def __init__(self, private_key: Ed25519PrivateKey, registry: SqliteReplayRegistry) -> None:
        self._private_key = private_key
        self.registry = registry

    @classmethod
    def generate(cls, registry: SqliteReplayRegistry) -> "ProvenanceAuthority":
        return cls(Ed25519PrivateKey.generate(), registry)

    def public_key_bytes(self) -> bytes:
        return self._private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )

    @property
    def key_id(self) -> str:
        return sha256_bytes(self.public_key_bytes())

    def issue(self, expectation: ProvenanceExpectation, *, nonce: str | None = None) -> SignedProvenanceToken:
        expectation_values = asdict(expectation)
        expectation_values["subjects"] = expectation.subjects
        payload = ProvenancePayload(
            schema=SCHEMA,
            key_id=self.key_id,
            nonce=nonce or secrets.token_hex(16),
            **expectation_values,
        )
        signature = self._private_key.sign(payload_bytes(payload))
        token = SignedProvenanceToken(
            payload=payload,
            signature_b64=base64.b64encode(signature).decode("ascii"),
            token_sha256=token_digest(payload, signature),
        )
        self.registry.register(token)
        return token


class ProvenanceVerifier:
    def __init__(self, public_key_bytes: bytes, registry: SqliteReplayRegistry) -> None:
        self._public_key = Ed25519PublicKey.from_public_bytes(public_key_bytes)
        self._key_id = sha256_bytes(public_key_bytes)
        self.registry = registry

    def verify_claims(
        self,
        token: SignedProvenanceToken,
        expectation: ProvenanceExpectation,
    ) -> str:
        """Verify authentication and semantic claims without changing registry state."""
        reasons: list[str] = []
        if token.payload.schema != SCHEMA:
            reasons.append("schema_mismatch")
        if token.payload.key_id != self._key_id:
            reasons.append("unknown_signing_key")
        try:
            signature = base64.b64decode(token.signature_b64, validate=True)
        except Exception:
            signature = b""
            reasons.append("invalid_signature_encoding")
        if signature and token.token_sha256 != token_digest(token.payload, signature):
            reasons.append("token_digest_mismatch")
        if signature:
            try:
                self._public_key.verify(signature, payload_bytes(token.payload))
            except InvalidSignature:
                reasons.append("invalid_signature")
        for field in fields(expectation):
            if getattr(token.payload, field.name) != getattr(expectation, field.name):
                reasons.append(f"claim_mismatch:{field.name}")
        if reasons:
            raise ProvenanceRejected(tuple(dict.fromkeys(reasons)))
        return sha256_bytes(payload_bytes(token.payload))

    def verify_and_consume(
        self,
        token: SignedProvenanceToken,
        expectation: ProvenanceExpectation,
        *,
        consumer_id: str,
    ) -> VerifiedProvenance:
        payload_sha256 = self.verify_claims(token, expectation)
        self.registry.consume(token.token_sha256, payload_sha256, consumer_id)
        return VerifiedProvenance(
            token_sha256=token.token_sha256,
            payload_sha256=payload_sha256,
            consumer_id=consumer_id,
            payload=token.payload,
        )


def _expectation() -> ProvenanceExpectation:
    subject = SubjectClaim("primary", "17", "a" * 64)
    return ProvenanceExpectation(
        run_id="run0",
        replay_sample_id="sample0",
        dataset_id="dataset",
        dataset_revision="rev0",
        split="train",
        dataset_manifest_sha256=dataset_manifest_digest({"17": subject.content_sha256}),
        epoch=3,
        sampler_context_sha256="b" * 64,
        subjects=(subject,),
        operator_path="augment/train",
        registration_sha256="c" * 64,
        input_content_sha256=subject.content_sha256,
    )


def self_test() -> dict[str, bool]:
    with tempfile.TemporaryDirectory(prefix="autocontract-h7l-") as directory:
        registry = SqliteReplayRegistry(Path(directory) / "registry.sqlite")
        authority = ProvenanceAuthority.generate(registry)
        verifier = ProvenanceVerifier(authority.public_key_bytes(), registry)
        expected = _expectation()

        token = authority.issue(expected)
        roundtrip = SignedProvenanceToken.from_json(token.to_json())
        verified = verifier.verify_and_consume(roundtrip, expected, consumer_id="worker0")

        try:
            verifier.verify_and_consume(token, expected, consumer_id="worker1")
            duplicate_rejected = False
        except ProvenanceRejected as error:
            duplicate_rejected = "token_consumed" in error.reasons

        mismatch_token = authority.issue(expected)
        wrong_expected = replace(expected, epoch=4)
        try:
            verifier.verify_and_consume(mismatch_token, wrong_expected, consumer_id="worker0")
            mismatch_rejected = False
        except ProvenanceRejected as error:
            mismatch_rejected = "claim_mismatch:epoch" in error.reasons
        not_burned = registry.state(mismatch_token.token_sha256) == "issued"
        verifier.verify_and_consume(mismatch_token, expected, consumer_id="worker0")

        tamper_token = authority.issue(expected)
        tampered_payload = replace(tamper_token.payload, epoch=99)
        forged_checksum = replace(
            tamper_token,
            payload=tampered_payload,
            token_sha256=token_digest(tampered_payload, base64.b64decode(tamper_token.signature_b64)),
        )
        try:
            verifier.verify_and_consume(forged_checksum, replace(expected, epoch=99), consumer_id="attacker")
            checksum_forgery_rejected = False
        except ProvenanceRejected as error:
            checksum_forgery_rejected = "invalid_signature" in error.reasons

        revoked = authority.issue(expected)
        registry.revoke(revoked.token_sha256)
        try:
            verifier.verify_and_consume(revoked, expected, consumer_id="worker0")
            revoked_rejected = False
        except ProvenanceRejected as error:
            revoked_rejected = "token_revoked" in error.reasons

        other_registry = registry
        other_authority = ProvenanceAuthority.generate(other_registry)
        wrong_key_token = other_authority.issue(expected)
        try:
            verifier.verify_and_consume(wrong_key_token, expected, consumer_id="worker0")
            wrong_key_rejected = False
        except ProvenanceRejected as error:
            wrong_key_rejected = "unknown_signing_key" in error.reasons and "invalid_signature" in error.reasons

        race_token = authority.issue(expected)
        race_success: list[str] = []
        race_reject: list[str] = []
        lock = threading.Lock()

        def racer(index: int) -> None:
            try:
                verifier.verify_and_consume(race_token, expected, consumer_id=f"race{index}")
                with lock:
                    race_success.append(str(index))
            except ProvenanceRejected as error:
                with lock:
                    race_reject.append(",".join(error.reasons))

        threads = [threading.Thread(target=racer, args=(index,)) for index in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        return {
            "signed_roundtrip": verified.token_sha256 == token.token_sha256,
            "duplicate_rejected": duplicate_rejected,
            "claim_mismatch_rejected_before_consume": mismatch_rejected and not_burned,
            "checksum_recompute_cannot_forge_signature": checksum_forgery_rejected,
            "revoked_rejected": revoked_rejected,
            "wrong_key_rejected": wrong_key_rejected,
            "four_way_race_exactly_one_success": len(race_success) == 1 and len(race_reject) == 3,
        }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not args.self_test:
        parser.error("--self-test is required")
    tests = self_test()
    payload = {
        "tests": tests,
        "passed": sum(tests.values()),
        "total": len(tests),
        "all_passed": all(tests.values()),
    }
    rendered = json.dumps(payload, indent=2)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    if not payload["all_passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
