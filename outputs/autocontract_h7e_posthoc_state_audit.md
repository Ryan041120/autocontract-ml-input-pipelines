# H7E posthoc state audit (non-gating)

This audit was designed after the formal one-shot H7E run and does not change H7E=PASS.

Replayable-parameter state detected: 6/7 units.

| Symbol | State writes | Role | Proposed obligation |
|---|---|---|---|
| `audiomentations.Normalize` | self.parameters | replayable_parameters | requires_parameters_unfrozen |
| `audiomentations.PolarityInversion` | self.parameters | replayable_parameters | requires_parameters_unfrozen |
| `audiomentations.AddGaussianNoise` | self.parameters | replayable_parameters | requires_parameters_unfrozen |
| `audiomentations.Clip` | self.parameters | replayable_parameters | requires_parameters_unfrozen |
| `audiomentations.Lambda` | self.parameters | replayable_parameters | requires_parameters_unfrozen |
| `audiomentations.Compose` | none | none | none |
| `audiomentations.AddBackgroundNoise` | self.parameters;self.time_info_arr | replayable_parameters+other_state | requires_parameters_unfrozen+audit_other_state |
