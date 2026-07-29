# AutoContract H7D zero-source TorchGeo holdout

Decisions correct: 4/5.
Known-unsafe false accepts: 0.
Safe recall: 75.0%.
Reason-category accuracy: 80.0%.
Resolved coverage: 80.0%.
H7D blind gate: **FAIL**.

| Unit | Status | Scope | Expected | Actual | Reason |
|---|---|---|---|---|---|
| `RandomGrayscale` | resolved | fixed_fields | admit | admit | none |
| `AppendNormalizedDifferenceIndex` | resolved | fixed_fields | admit | admit | none |
| `AppendTriBandNormalizedDifferenceIndex` | resolved | fixed_fields | admit | admit | none |
| `Rearrange` | unknown | unknown | admit | reject | sealed_source_unit_missing:Rearrange |
| `SatSlideMix` | resolved | fixed_fields | reject | reject | unsupported_cardinality:one->many |

The adapter was written from public interface documentation before repository source blobs were opened.
