"""Graph-based placement search over HeteroPilot's planner.

One-way dependency: this package imports `planner.*` from
`vendor/heteropilot` and nothing there knows this package exists. The
precedent is ScenarioLab (heteropilot `docs/deviations.md` D24).
"""
