"""Central weights and thresholds for dynamic task prioritization."""

PRIORITY_CONFIG = {
    "thresholds": {
        "plausible_decline_pct": 20.0,
        "plausible_previous_visitors": 20,
        "search_console_click_decline_pct": 0.0,
        "ctr_decline": 0.0,
        "position_worsening": 0.0,
        "critical_total_score": 70.0,
        "high_total_score": 20.0,
        "medium_total_score": 10.0,
    },
    "weights": {
        "plausible_base": 20.0,
        "plausible_per_percentage_point": 0.5,
        "plausible_max": 50.0,
        "search_console_click_per_percentage_point": 0.6,
        "search_console_click_max": 45.0,
        "ctr_per_percentage_point": 8.0,
        "ctr_max": 30.0,
        "position_per_position": 4.0,
        "position_max": 30.0,
        "seo_health_critical": 50.0,
        "seo_health_declining": 30.0,
        "experiment_active": 10.0,
        "experiment_ready": 35.0,
        "missing_search_console": 25.0,
        "missing_plausible": 15.0,
        "system_error": 100.0,
        "existing_task_multiplier": 0.3,
    },
}
