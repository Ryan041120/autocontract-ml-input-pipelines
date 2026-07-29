# H7L registry storage ablation

Randomized rounds: 10; operations per within-round median: 10; persistent connection per registry.

| Storage | Issue+register | Consume | Rounds |
|---|---:|---:|---:|
| workspace_onedrive | 5.265 ms | 4.588 ms | 10 |
| local_temp | 4.846 ms | 4.279 ms | 10 |

Workspace/local consume ratio: 1.072x.
The comparison isolates storage placement, not SQLite versus alternative registry architectures.
