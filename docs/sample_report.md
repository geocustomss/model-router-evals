## Overall

| model | pass rate | avg latency (ms) | total cost (USD) | cost per pass (USD) |
|---|---|---|---|---|
| mock/mock-large | 8/8 (100%) | 0.0 | 0.000375 | 0.000047 |
| mock/mock-small | 3/8 (38%) | 0.0 | 0.000041 | 0.000014 |

## By task

| task | model | pass rate | cost (USD) |
|---|---|---|---|
| classify | mock/mock-large | 3/3 | 0.000109 |
| classify | mock/mock-small | 3/3 | 0.000011 |
| extract_json | mock/mock-large | 2/2 | 0.000108 |
| extract_json | mock/mock-small | 0/2 | 0.000007 |
| reasoning | mock/mock-large | 2/2 | 0.000038 |
| reasoning | mock/mock-small | 0/2 | 0.000004 |
| summarize | mock/mock-large | 1/1 | 0.000120 |
| summarize | mock/mock-small | 0/1 | 0.000019 |

## Recommended routes (cheapest model with pass rate >= 90%)

- **classify** -> `mock/mock-small` (100%, $0.000011)
- **extract_json** -> `mock/mock-large` (100%, $0.000108)
- **reasoning** -> `mock/mock-large` (100%, $0.000038)
- **summarize** -> `mock/mock-large` (100%, $0.000120)
