"""
Audit module registry — single source of truth for which modules run per mode.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import boto3


def get_audit_module_classes(
    teaser: bool = False,
    teaser_sources: str = "light",
) -> list[type]:
    """
    Return module classes to run for the given audit mode.

    teaser_sources (only when teaser=True):
      ta-only  — Trusted Advisor cost checks only (~30s)
      light    — TA + fast API-only custom checks (default, ~2-3 min/region)
      standard — all modules with teaser=True flags (legacy behaviour)
    """
    from integrations.aws_recommendations import AwsRecommendationsModule
    from modules.compute_strategy import ComputeStrategyModule
    from modules.database_tuning import DatabaseTuningModule
    from modules.infra_hygiene import InfraHygieneModule
    from modules.network_storage import NetworkStorageModule
    from modules.observability_cost import ObservabilityCostModule
    from modules.savings_plans import SavingsPlansModule

    if not teaser:
        return [
            AwsRecommendationsModule,
            InfraHygieneModule,
            ComputeStrategyModule,
            NetworkStorageModule,
            ObservabilityCostModule,
            DatabaseTuningModule,
            SavingsPlansModule,
        ]

    if teaser_sources == "ta-only":
        return [AwsRecommendationsModule]

    if teaser_sources == "standard":
        return [
            AwsRecommendationsModule,
            InfraHygieneModule,
            ComputeStrategyModule,
            NetworkStorageModule,
            ObservabilityCostModule,
            DatabaseTuningModule,
            SavingsPlansModule,
        ]

    # light (default)
    return [
        AwsRecommendationsModule,
        InfraHygieneModule,
        NetworkStorageModule,
        ObservabilityCostModule,
    ]
