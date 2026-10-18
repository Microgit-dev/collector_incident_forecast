from apps.forecasting.domain import features as F
from apps.forecasting.management.commands.benchmark_node_context import without_node_context


def test_node_ablation_preserves_all_other_features():
    columns = F.FEATURES + F.EXTRA_FEATURES
    selected = without_node_context(columns)
    assert set(columns) - set(selected) == {"node_faults_1", "node_faults_7", "node_power_1", "node_power_7"}
    assert "faults_7" in selected and "power_7" in selected
    assert F.CATEGORICAL[0] in selected and F.CATEGORICAL[1] in selected
