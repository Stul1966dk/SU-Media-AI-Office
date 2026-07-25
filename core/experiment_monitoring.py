"""Live, cautious monitoring of active SEO experiments."""

import json
from datetime import date, datetime
from typing import Any


class ExperimentMonitoringService:
    """Turn stored Search Console periods into pulse and milestone events."""

    def __init__(self, database: Any) -> None:
        self.database = database

    def update_active_experiments(
        self, reference_date: date | None = None,
        website_ids: set[str] | None = None,
        due_only: bool = False,
    ) -> list[dict[str, Any]]:
        today = reference_date or date.today()
        active = self.database.get_seo_experiments(statuses=(
            "approved", "running", "waiting_for_data", "ready_for_evaluation",
        ))
        selected = [
            item for item in active
            if website_ids is None or item["website_id"] in website_ids
        ]
        if due_only:
            selected = [
                item for item in selected
                if item.get("planned_evaluation_date")
                and date.fromisoformat(item["planned_evaluation_date"]) <= today
            ]
        return [self.update_experiment(item["id"], today) for item in selected]

    def update_experiment(
        self, experiment_id: int, reference_date: date | None = None
    ) -> dict[str, Any]:
        today = reference_date or date.today()
        experiment = self.database.get_seo_experiment(experiment_id)
        if not experiment:
            raise ValueError("Eksperimentet findes ikke.")
        if experiment.get("started_at"):
            self.database.save_experiment_observation(
                experiment_id=experiment_id,
                observation_date=experiment["started_at"][:10],
                observation_type="implementeret",
                event_key="implemented",
                description="Ændringen blev markeret som implementeret.",
            )
        measurement = self._latest_measurement(experiment)
        if not measurement:
            return {
                "experiment_id": experiment_id,
                "pulse_status": "Afventer data",
                "observation": "Der er endnu ingen nye Search Console-data.",
                "data_changed": False,
            }
        days = self._days_since(experiment.get("started_at"), today)
        quality = self._data_quality(measurement)
        pulse, observation = self._pulse(
            experiment, measurement, days, quality
        )
        status_changed = False
        if (
            experiment.get("planned_evaluation_date")
            and date.fromisoformat(experiment["planned_evaluation_date"]) <= today
        ):
            pulse = "Klar til evaluering"
            observation = (
                "Måleperioden er afsluttet. Eksperimentet kan nu evalueres."
            )
            self.database.update_seo_experiment(
                experiment_id, {"status": "ready_for_evaluation"}
            )
            status_changed = experiment.get("status") != "ready_for_evaluation"
            self._observation(
                experiment_id, today, "klar til evaluering",
                "ready-for-evaluation", observation,
            )
        snapshot_created = self.database.save_experiment_snapshot({
            "experiment_id": experiment_id,
            "observed_date": today.isoformat(),
            "period_start": measurement["period_start"],
            "period_end": measurement["period_end"],
            "clicks": measurement["clicks"],
            "impressions": measurement["impressions"],
            "ctr": measurement["ctr"],
            "average_position": measurement["average_position"],
            "data_quality": quality,
            "pulse_status": pulse, "observation": observation,
        })
        self._milestones(experiment, measurement, quality, today)
        return {
            "experiment_id": experiment_id, "pulse_status": pulse,
            "observation": observation, "data_quality": quality,
            "data_changed": bool(snapshot_created or status_changed),
            **measurement,
        }

    def latest_updates(self, limit: int = 3) -> list[dict[str, Any]]:
        observations = self.database.get_experiment_observations()
        meaningful = {
            "positiv placering", "negativ placering", "CTR-milepæl",
            "klik-milepæl", "top-10", "top-5", "top-3",
            "klar til evaluering", "afsluttet",
        }
        return [
            item for item in observations
            if item["observation_type"] in meaningful
        ][:limit]

    def _latest_measurement(
        self, experiment: dict[str, Any]
    ) -> dict[str, Any] | None:
        dimension = "page_query" if experiment.get("target_query") else "page"
        rows = self.database.get_search_console_dimensions(
            dimension, website_id=experiment["website_id"],
            page_url=experiment["target_url"],
        )
        if experiment.get("target_query"):
            rows = [
                item for item in rows
                if item.get("query") == experiment["target_query"]
            ]
        if not rows:
            return None
        return max(rows, key=lambda item: item["period_end"])

    @staticmethod
    def _days_since(started_at: str | None, today: date) -> int:
        if not started_at:
            return 0
        return max(
            0, (today - datetime.fromisoformat(started_at).date()).days + 1
        )

    @staticmethod
    def _data_quality(measurement: dict[str, Any]) -> str:
        days = (
            date.fromisoformat(measurement["period_end"])
            - date.fromisoformat(measurement["period_start"])
        ).days + 1
        impressions = int(measurement["impressions"])
        clicks = int(measurement["clicks"])
        if days >= 21 and impressions >= 500 and clicks >= 20:
            return "Høj"
        if days >= 14 and impressions >= 100 and clicks >= 5:
            return "Middel"
        return "Lav"

    @staticmethod
    def _pulse(
        experiment: dict[str, Any], current: dict[str, Any],
        days: int, quality: str,
    ) -> tuple[str, str]:
        if days < 3 or quality == "Lav":
            return (
                "Indsamler data",
                "De første data er tilgængelige, men datamængden er fortsat "
                "for begrænset til en konklusion.",
            )
        baseline_ctr = float(experiment.get("baseline_ctr") or 0)
        baseline_position = float(experiment.get("baseline_position") or 0)
        ctr_change = (
            (float(current["ctr"]) - baseline_ctr) / baseline_ctr * 100
            if baseline_ctr else 0
        )
        position_gain = baseline_position - float(current["average_position"])
        if ctr_change >= 10 or position_gain >= 1:
            return (
                "Positiv udvikling",
                "De første data ser positive ud. Placering eller CTR er "
                "forbedret, men eksperimentet fortsætter til evalueringsdatoen.",
            )
        if ctr_change <= -10 or position_gain <= -1:
            return (
                "Negativ udvikling",
                "Siden har haft tilbagegang, men eksperimentet fortsætter til "
                "evalueringsdatoen.",
            )
        return (
            "Stabil udvikling",
            "Udviklingen er endnu ikke tydelig. Resultaterne ligger tæt på "
            "udgangspunktet.",
        )

    def _milestones(
        self, experiment: dict[str, Any], current: dict[str, Any],
        quality: str, today: date,
    ) -> None:
        if quality == "Lav":
            return
        position = float(current["average_position"])
        for threshold, kind in ((10, "top-10"), (5, "top-5"), (3, "top-3")):
            if position <= threshold:
                self._observation(
                    experiment["id"], today, kind, kind,
                    f"Siden er for første gang i måleperioden placeret i {kind}.",
                )
        baseline_position = float(experiment.get("baseline_position") or 0)
        gain = baseline_position - position
        if gain >= 1:
            self._observation(
                experiment["id"], today, "positiv placering",
                "position-improved-1",
                f"Placeringen er forbedret fra {baseline_position:.1f} "
                f"til {position:.1f}.",
            )
        elif gain <= -1:
            self._observation(
                experiment["id"], today, "negativ placering",
                "position-declined-1",
                f"Placeringen er faldet fra {baseline_position:.1f} "
                f"til {position:.1f}.",
            )
        baseline_ctr = float(experiment.get("baseline_ctr") or 0)
        if baseline_ctr:
            ctr_pct = (float(current["ctr"]) - baseline_ctr) / baseline_ctr * 100
            for threshold in (10, 20):
                if ctr_pct >= threshold:
                    self._observation(
                        experiment["id"], today, "CTR-milepæl",
                        f"ctr-{threshold}",
                        f"CTR er forbedret mindst {threshold} %.",
                    )

    def _observation(
        self, experiment_id: int, observed: date, kind: str,
        event_key: str, description: str,
    ) -> None:
        created = self.database.save_experiment_observation(
            experiment_id=experiment_id,
            observation_date=observed.isoformat(),
            observation_type=kind, event_key=event_key,
            description=description,
        )
        meaningful = {
            "positiv placering", "negativ placering", "CTR-milepæl",
            "klik-milepæl", "top-10", "top-5", "top-3",
            "klar til evaluering", "afsluttet",
        }
        if created and kind in meaningful:
            experiment = self.database.get_seo_experiment(experiment_id) or {}
            timestamp = datetime.now().astimezone().isoformat(
                timespec="seconds"
            )
            self.database.create_event_record({
                "event_type": "seo_experiment_update",
                "source": "experiment_monitoring",
                "website": experiment.get("website_id", ""),
                "title": kind.capitalize(),
                "description": description,
                "priority": 80 if kind in {
                    "negativ placering", "klar til evaluering"
                } else 60,
                "data_json": json.dumps({
                    "experiment_id": experiment_id,
                    "observation_type": kind,
                }),
                "status": "pending", "created_at": timestamp,
            })
