# Scenarios

预设仿真场景配置文件（YAML 格式）。

| 文件 | 描述 | 阶段 |
|------|------|------|
| `baseline.yaml` | 基准稳态，无外部冲击 | Phase 0 |
| `loose_credit.yaml` | 宽松信贷：低利率 + 高 LTV | Phase 2 |
| `tight_credit.yaml` | 紧信贷：高利率 + 严 LTV | Phase 2 |
| `energy_shock.yaml` | 能源供给冲击 | Phase 1 |
| `volcker_shock.yaml` | 激进加息抗通胀 | Phase 1 |
| `fiscal_stimulus.yaml` | 财政刺激实验 | Phase 2 |

格式参考 `SimConfig` (financial_sim/config.py)。
