# Third-party research corpora

AutoContract analyzes frozen versions of external ML preprocessing libraries.
The repositories below remain separate upstream works and are recorded as Git
submodules at the exact commits used by the experiments.

| Local path | Upstream repository | Frozen commit |
|---|---|---|
| `.research/semantics_safe_reconfiguration/h7c_corpus/torchio_repo` | <https://github.com/TorchIO-project/torchio.git> | `3ee81f2991300c3c982aa31575d40d3838593063` |
| `.research/semantics_safe_reconfiguration/h7d_corpus/torchgeo_repo` | <https://github.com/torchgeo/torchgeo.git> | `120b8b1d477e8911ed052ec84a197dd545254e63` |
| `.research/semantics_safe_reconfiguration/h7e_corpus/audiomentations_repo` | <https://github.com/iver56/audiomentations.git> | `19609e6d6624ef9e4933412ccda78fb6221f77e1` |
| `.research/semantics_safe_reconfiguration/h7f_corpus/imgaug_repo` | <https://github.com/aleju/imgaug.git> | `14b85e2209de0107c250e4d9dd6507dec1eae826` |
| `.research/semantics_safe_reconfiguration/h7g_corpus/albumentations_repo` | <https://github.com/albumentations-team/albumentations.git> | `4d2cf04b6635663275a747333754410ef255e54c` |
| `.research/semantics_safe_reconfiguration/h7h_corpus/kornia_repo` | <https://github.com/kornia/kornia.git> | `d6bb4bf0d8a043c2bb8cef0c346a1b006d100930` |

Additional H6/H7B source snapshots are identified by repository, commit and
path in the checked-in `outputs/*freeze.json` manifests. They are retained as
research corpus evidence; their upstream licenses and copyrights continue to
apply. No ownership of third-party source code is claimed here.

Before changing repository visibility from private to public, perform a
separate license review of all snapshots and submodules.
