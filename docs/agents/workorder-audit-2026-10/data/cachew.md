# Cache-write attribution (tokens)

| context | spawn/first request | after idle gap > TTL (expiry) | incremental growth | expiry events |
|---|---:|---:|---:|---:|
| main | 6M (12%) | 27M (48%) | 22M (40%) | 94 |
| subagent | 35M (25%) | 18M (13%) | 88M (62%) | 106 |
| workflow | 148M (45%) | 3M (1%) | 175M (54%) | 56 |