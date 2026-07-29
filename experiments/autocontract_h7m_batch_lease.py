"""H7M signed Merkle batches with fenced lease/commit registry."""

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
from typing import Literal

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

import autocontract_h7l_provenance_token as h7l


SCHEMA = "autocontract.batch-provenance/v1"
Side = Literal["left", "right"]


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _leaf_hash(value: bytes) -> bytes:
    return hashlib.sha256(b"\x00" + value).digest()


def _node_hash(left: bytes, right: bytes) -> bytes:
    return hashlib.sha256(b"\x01" + left + right).digest()


EMPTY_LEAF = _leaf_hash(b"")


@dataclass(frozen=True)
class BatchLeaf:
    index: int
    expectation: h7l.ProvenanceExpectation
    nonce: str


@dataclass(frozen=True)
class BatchRootStatement:
    schema: str
    key_id: str
    batch_id: str
    tree_size: int
    merkle_root_sha256: str
    context_sha256: str


@dataclass(frozen=True)
class SignedBatchRoot:
    statement: BatchRootStatement
    signature_b64: str
    attestation_sha256: str


@dataclass(frozen=True)
class ProofNode:
    side: Side
    sha256: str


@dataclass(frozen=True)
class BatchTicket:
    leaf: BatchLeaf
    proof: tuple[ProofNode, ...]
    root: SignedBatchRoot


@dataclass(frozen=True)
class BatchLease:
    batch_id: str
    lease_id: str
    worker_id: str
    generation: int


@dataclass(frozen=True)
class BatchCommitReceipt:
    batch_id: str
    lease_id: str
    generation: int
    output_sha256: str
    idempotent: bool


class BatchRejected(RuntimeError):
    def __init__(self, reasons: tuple[str, ...]) -> None:
        super().__init__("batch rejected: " + ",".join(reasons))
        self.reasons = reasons


def _expectation_record(expectation: h7l.ProvenanceExpectation) -> dict[str, object]:
    record = asdict(expectation)
    record["subjects"] = [asdict(subject) for subject in expectation.subjects]
    return record


def _leaf_bytes(leaf: BatchLeaf) -> bytes:
    return h7l.canonical_bytes({
        "index": leaf.index,
        "expectation": _expectation_record(leaf.expectation),
        "nonce": leaf.nonce,
    })


def _statement_bytes(statement: BatchRootStatement) -> bytes:
    return h7l.canonical_bytes(asdict(statement))


def _attestation_digest(statement: BatchRootStatement, signature: bytes) -> str:
    return _sha(_statement_bytes(statement) + b"." + signature)


def batch_context_digest(expectations: tuple[h7l.ProvenanceExpectation, ...]) -> str:
    if not expectations:
        raise BatchRejected(("empty_batch",))
    names = (
        "run_id",
        "dataset_id",
        "dataset_revision",
        "split",
        "dataset_manifest_sha256",
        "epoch",
        "sampler_context_sha256",
        "operator_path",
    )
    first = expectations[0]
    context = {name: getattr(first, name) for name in names}
    if any(any(getattr(item, name) != context[name] for name in names) for item in expectations[1:]):
        raise BatchRejected(("heterogeneous_batch_context",))
    return _sha(h7l.canonical_bytes(context))


def _tree_levels(leaves: tuple[BatchLeaf, ...]) -> list[list[bytes]]:
    if not leaves:
        raise BatchRejected(("empty_batch",))
    level = [_leaf_hash(_leaf_bytes(leaf)) for leaf in leaves]
    width = 1
    while width < len(level):
        width <<= 1
    level.extend([EMPTY_LEAF] * (width - len(level)))
    levels = [level]
    while len(level) > 1:
        level = [_node_hash(level[index], level[index + 1]) for index in range(0, len(level), 2)]
        levels.append(level)
    return levels


def _proof(levels: list[list[bytes]], index: int) -> tuple[ProofNode, ...]:
    proof: list[ProofNode] = []
    cursor = index
    for level in levels[:-1]:
        sibling = cursor ^ 1
        side: Side = "left" if sibling < cursor else "right"
        proof.append(ProofNode(side, level[sibling].hex()))
        cursor //= 2
    return tuple(proof)


class BatchAuthority:
    def __init__(self, private_key: Ed25519PrivateKey) -> None:
        self._private_key = private_key

    @classmethod
    def generate(cls) -> "BatchAuthority":
        return cls(Ed25519PrivateKey.generate())

    def public_key_bytes(self) -> bytes:
        return self._private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )

    @property
    def key_id(self) -> str:
        return _sha(self.public_key_bytes())

    def issue_batch(
        self,
        expectations: tuple[h7l.ProvenanceExpectation, ...],
        *,
        batch_id: str,
    ) -> tuple[BatchTicket, ...]:
        if len(expectations) < 1:
            raise BatchRejected(("empty_batch",))
        leaves = tuple(
            BatchLeaf(index, expectation, secrets.token_hex(16))
            for index, expectation in enumerate(expectations)
        )
        levels = _tree_levels(leaves)
        statement = BatchRootStatement(
            schema=SCHEMA,
            key_id=self.key_id,
            batch_id=batch_id,
            tree_size=len(leaves),
            merkle_root_sha256=levels[-1][0].hex(),
            context_sha256=batch_context_digest(expectations),
        )
        signature = self._private_key.sign(_statement_bytes(statement))
        root = SignedBatchRoot(
            statement=statement,
            signature_b64=base64.b64encode(signature).decode("ascii"),
            attestation_sha256=_attestation_digest(statement, signature),
        )
        return tuple(BatchTicket(leaf, _proof(levels, leaf.index), root) for leaf in leaves)


class BatchVerifier:
    def __init__(self, public_key_bytes: bytes) -> None:
        self._public_key = Ed25519PublicKey.from_public_bytes(public_key_bytes)
        self._key_id = _sha(public_key_bytes)
        self._verified_roots: set[str] = set()
        self._lock = threading.Lock()
        self.signature_verifications = 0

    def _verify_root(self, root: SignedBatchRoot) -> None:
        reasons: list[str] = []
        statement = root.statement
        if statement.schema != SCHEMA:
            reasons.append("batch_schema_mismatch")
        if statement.key_id != self._key_id:
            reasons.append("unknown_batch_key")
        try:
            signature = base64.b64decode(root.signature_b64, validate=True)
        except Exception:
            signature = b""
            reasons.append("invalid_batch_signature_encoding")
        computed_attestation = _attestation_digest(statement, signature) if signature else ""
        if signature and root.attestation_sha256 != computed_attestation:
            reasons.append("batch_attestation_digest_mismatch")
        if reasons:
            raise BatchRejected(tuple(reasons))
        with self._lock:
            if computed_attestation in self._verified_roots:
                return
            if signature:
                try:
                    self._public_key.verify(signature, _statement_bytes(statement))
                except InvalidSignature:
                    reasons.append("invalid_batch_signature")
            if reasons:
                raise BatchRejected(tuple(reasons))
            self._verified_roots.add(computed_attestation)
            self.signature_verifications += 1

    def verify_ticket(self, ticket: BatchTicket, expected: h7l.ProvenanceExpectation) -> None:
        self._verify_root(ticket.root)
        statement = ticket.root.statement
        reasons: list[str] = []
        if ticket.leaf.index < 0 or ticket.leaf.index >= statement.tree_size:
            reasons.append("leaf_index_out_of_range")
        if ticket.leaf.expectation != expected:
            reasons.append("leaf_claim_mismatch")
        if statement.context_sha256 != batch_context_digest((ticket.leaf.expectation,)):
            reasons.append("batch_context_mismatch")
        cursor = _leaf_hash(_leaf_bytes(ticket.leaf))
        for node in ticket.proof:
            try:
                sibling = bytes.fromhex(node.sha256)
            except ValueError:
                reasons.append("invalid_merkle_proof_encoding")
                break
            if len(sibling) != 32:
                reasons.append("invalid_merkle_proof_length")
                break
            cursor = _node_hash(sibling, cursor) if node.side == "left" else _node_hash(cursor, sibling)
        if cursor.hex() != statement.merkle_root_sha256:
            reasons.append("merkle_inclusion_mismatch")
        if reasons:
            raise BatchRejected(tuple(dict.fromkeys(reasons)))

    def verify_batch(
        self,
        tickets: tuple[BatchTicket, ...],
        expectations: tuple[h7l.ProvenanceExpectation, ...],
    ) -> SignedBatchRoot:
        if not tickets or len(tickets) != len(expectations):
            raise BatchRejected(("batch_length_mismatch",))
        root = tickets[0].root
        if root.statement.tree_size != len(tickets):
            raise BatchRejected(("tree_size_mismatch",))
        for index, (ticket, expected) in enumerate(zip(tickets, expectations)):
            if ticket.root != root:
                raise BatchRejected(("mixed_batch_roots",))
            if ticket.leaf.index != index:
                raise BatchRejected(("ticket_order_mismatch",))
            self.verify_ticket(ticket, expected)
        return root


class SqliteBatchRegistry:
    def __init__(self, path: Path, *, reset: bool = False, persistent_connections: bool = False) -> None:
        self.path = Path(path)
        self._persistent = persistent_connections
        self._local = threading.local()
        if reset and self.path.exists():
            self.path.unlink()
        connection = self._connect()
        try:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS provenance_batches (
                    batch_id TEXT PRIMARY KEY,
                    attestation_sha256 TEXT NOT NULL,
                    merkle_root_sha256 TEXT NOT NULL,
                    tree_size INTEGER NOT NULL,
                    state TEXT NOT NULL CHECK(state IN ('issued','leased','committed','revoked')),
                    generation INTEGER NOT NULL,
                    lease_id TEXT,
                    worker_id TEXT,
                    output_sha256 TEXT,
                    updated_ns INTEGER NOT NULL
                )
                """
            )
            connection.commit()
        finally:
            connection.close()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30.0, isolation_level=None)
        connection.execute("PRAGMA busy_timeout=30000")
        return connection

    def _acquire(self) -> tuple[sqlite3.Connection, bool]:
        if not self._persistent:
            return self._connect(), True
        connection = getattr(self._local, "connection", None)
        if connection is None:
            connection = self._connect()
            self._local.connection = connection
        return connection, False

    def _release(self, connection: sqlite3.Connection, owned: bool) -> None:
        if owned:
            connection.close()

    def close(self) -> None:
        connection = getattr(self._local, "connection", None)
        if connection is not None:
            connection.close()
            del self._local.connection

    def register(self, root: SignedBatchRoot) -> None:
        statement = root.statement
        connection, owned = self._acquire()
        try:
            connection.execute(
                "INSERT INTO provenance_batches VALUES (?,?,?,?, 'issued',0,NULL,NULL,NULL,?)",
                (
                    statement.batch_id,
                    root.attestation_sha256,
                    statement.merkle_root_sha256,
                    statement.tree_size,
                    time.time_ns(),
                ),
            )
            connection.commit()
        except sqlite3.IntegrityError as error:
            raise BatchRejected(("batch_already_registered",)) from error
        finally:
            self._release(connection, owned)

    def claim(self, batch_id: str, worker_id: str) -> BatchLease:
        connection, owned = self._acquire()
        try:
            connection.execute("BEGIN IMMEDIATE")
            record = connection.execute(
                "SELECT state,generation FROM provenance_batches WHERE batch_id=?", (batch_id,),
            ).fetchone()
            if record is None:
                raise BatchRejected(("batch_not_registered",))
            state, generation = str(record[0]), int(record[1])
            if state != "issued":
                raise BatchRejected((f"batch_{state}",))
            lease = BatchLease(batch_id, secrets.token_hex(16), worker_id, generation + 1)
            cursor = connection.execute(
                "UPDATE provenance_batches SET state='leased',generation=?,lease_id=?,worker_id=?,updated_ns=? "
                "WHERE batch_id=? AND state='issued' AND generation=?",
                (lease.generation, lease.lease_id, worker_id, time.time_ns(), batch_id, generation),
            )
            if cursor.rowcount != 1:
                raise BatchRejected(("batch_claim_race_lost",))
            connection.commit()
            return lease
        except Exception:
            connection.rollback()
            raise
        finally:
            self._release(connection, owned)

    def recover(self, lease: BatchLease) -> None:
        connection, owned = self._acquire()
        try:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                "UPDATE provenance_batches SET state='issued',generation=generation+1,lease_id=NULL,worker_id=NULL,updated_ns=? "
                "WHERE batch_id=? AND state='leased' AND lease_id=? AND generation=?",
                (time.time_ns(), lease.batch_id, lease.lease_id, lease.generation),
            )
            if cursor.rowcount != 1:
                raise BatchRejected(("lease_recovery_mismatch",))
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            self._release(connection, owned)

    def abort(self, lease: BatchLease) -> None:
        self.recover(lease)

    def commit(self, lease: BatchLease, output_sha256: str) -> BatchCommitReceipt:
        connection, owned = self._acquire()
        try:
            connection.execute("BEGIN IMMEDIATE")
            record = connection.execute(
                "SELECT state,generation,lease_id,output_sha256 FROM provenance_batches WHERE batch_id=?",
                (lease.batch_id,),
            ).fetchone()
            if record is None:
                raise BatchRejected(("batch_not_registered",))
            state, generation, lease_id, stored_output = str(record[0]), int(record[1]), record[2], record[3]
            matches = generation == lease.generation and lease_id == lease.lease_id
            if state == "committed":
                if matches and stored_output == output_sha256:
                    connection.commit()
                    return BatchCommitReceipt(lease.batch_id, lease.lease_id, lease.generation, output_sha256, True)
                raise BatchRejected(("committed_batch_conflict",))
            if state != "leased" or not matches:
                raise BatchRejected(("stale_or_invalid_lease",))
            connection.execute(
                "UPDATE provenance_batches SET state='committed',output_sha256=?,updated_ns=? WHERE batch_id=?",
                (output_sha256, time.time_ns(), lease.batch_id),
            )
            connection.commit()
            return BatchCommitReceipt(lease.batch_id, lease.lease_id, lease.generation, output_sha256, False)
        except Exception:
            connection.rollback()
            raise
        finally:
            self._release(connection, owned)

    def state(self, batch_id: str) -> dict[str, object] | None:
        connection, owned = self._acquire()
        try:
            record = connection.execute(
                "SELECT state,generation,lease_id,worker_id,output_sha256 FROM provenance_batches WHERE batch_id=?",
                (batch_id,),
            ).fetchone()
            if record is None:
                return None
            return {
                "state": str(record[0]),
                "generation": int(record[1]),
                "lease_id": record[2],
                "worker_id": record[3],
                "output_sha256": record[4],
            }
        finally:
            self._release(connection, owned)


def _expectations(size: int) -> tuple[h7l.ProvenanceExpectation, ...]:
    records = {str(index): _sha(f"sample-{index}".encode()) for index in range(size)}
    manifest = h7l.dataset_manifest_digest(records)
    return tuple(
        h7l.ProvenanceExpectation(
            run_id="batch/run0",
            replay_sample_id=f"sample/{index}",
            dataset_id="batch-dataset",
            dataset_revision="rev0",
            split="train",
            dataset_manifest_sha256=manifest,
            epoch=2,
            sampler_context_sha256="a" * 64,
            subjects=(h7l.SubjectClaim("primary", str(index), records[str(index)]),),
            operator_path="train/augment",
            registration_sha256="b" * 64,
            input_content_sha256=records[str(index)],
        )
        for index in range(size)
    )


def self_test() -> dict[str, bool]:
    authority = BatchAuthority.generate()
    verifier = BatchVerifier(authority.public_key_bytes())
    expected = _expectations(8)
    tickets = authority.issue_batch(expected, batch_id="batch0")
    verifier.verify_batch(tickets, expected)

    tampered_leaf = replace(tickets[0].leaf, nonce="tampered")
    try:
        verifier.verify_ticket(replace(tickets[0], leaf=tampered_leaf), expected[0])
        leaf_rejected = False
    except BatchRejected as error:
        leaf_rejected = "merkle_inclusion_mismatch" in error.reasons
    tampered_proof = replace(tickets[1].proof[0], sha256="0" * 64)
    try:
        verifier.verify_ticket(replace(tickets[1], proof=(tampered_proof,) + tickets[1].proof[1:]), expected[1])
        proof_rejected = False
    except BatchRejected as error:
        proof_rejected = "merkle_inclusion_mismatch" in error.reasons

    with tempfile.TemporaryDirectory(prefix="autocontract-h7m-") as directory:
        registry = SqliteBatchRegistry(Path(directory) / "registry.sqlite")
        registry.register(tickets[0].root)
        lease = registry.claim("batch0", "worker0")
        committed = registry.commit(lease, "c" * 64)
        idempotent = registry.commit(lease, "c" * 64)
        try:
            registry.commit(lease, "d" * 64)
            conflict_rejected = False
        except BatchRejected as error:
            conflict_rejected = "committed_batch_conflict" in error.reasons

        crash_tickets = authority.issue_batch(_expectations(4), batch_id="crash")
        registry.register(crash_tickets[0].root)
        stale = registry.claim("crash", "dead-worker")
        registry.recover(stale)
        replacement = registry.claim("crash", "replacement")
        try:
            registry.commit(stale, "e" * 64)
            stale_rejected = False
        except BatchRejected as error:
            stale_rejected = "stale_or_invalid_lease" in error.reasons
        replacement_commit = registry.commit(replacement, "e" * 64)

        race_tickets = authority.issue_batch(_expectations(4), batch_id="race")
        registry.register(race_tickets[0].root)
        winners: list[BatchLease] = []
        losers: list[str] = []
        lock = threading.Lock()

        def racer(index: int) -> None:
            try:
                won = registry.claim("race", f"worker{index}")
                with lock:
                    winners.append(won)
            except BatchRejected as error:
                with lock:
                    losers.append(",".join(error.reasons))

        threads = [threading.Thread(target=racer, args=(index,)) for index in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

    return {
        "batch_and_all_inclusion_proofs_valid": verifier.signature_verifications == 1,
        "tampered_leaf_rejected": leaf_rejected,
        "tampered_proof_rejected": proof_rejected,
        "commit_and_ack_retry_idempotent": not committed.idempotent and idempotent.idempotent,
        "conflicting_ack_retry_rejected": conflict_rejected,
        "recovery_fences_stale_worker": stale_rejected and replacement_commit.generation == replacement.generation,
        "four_way_claim_exactly_one_winner": len(winners) == 1 and len(losers) == 3,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not args.self_test:
        parser.error("--self-test is required")
    tests = self_test()
    payload = {"tests": tests, "passed": sum(tests.values()), "total": len(tests), "all_passed": all(tests.values())}
    rendered = json.dumps(payload, indent=2)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    if not payload["all_passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
