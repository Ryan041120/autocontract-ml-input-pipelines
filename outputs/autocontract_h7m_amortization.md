# H7M Merkle-batch amortization

Independent rounds per batch size: 10. H7L uses N signed/registered/consumed tokens; H7M uses one signed root plus one register, claim, and commit per batch.

| N | H7L issue/sample | H7M issue/sample | H7L consume/sample | H7M consume/sample | H7M/H7L consumer | H7L bytes/sample | H7M bytes/sample |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 3.695 ms | 3.668 ms | 3.657 ms | 7.068 ms | 1.911x | 1021 | 1297 |
| 4 | 3.749 ms | 0.970 ms | 3.838 ms | 1.852 ms | 0.488x | 1021 | 1072 |
| 16 | 3.971 ms | 0.299 ms | 4.171 ms | 0.564 ms | 0.138x | 1022 | 1156 |
| 64 | 4.088 ms | 0.116 ms | 4.217 ms | 0.217 ms | 0.053x | 1023 | 1317 |

H7M uses two consumer-side durable transitions (claim and commit) per batch, so N=1 is expected to lose. The compact-wire calculation sends the signed root once per batch and leaf/proof data per sample.
