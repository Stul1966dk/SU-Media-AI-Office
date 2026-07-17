"""SEO Manager specialist agent for evidence-based recovery planning."""

from dataclasses import dataclass
from datetime import date
from typing import Any

from agents.project_manager import ProjectManager
from core.agent_orchestrator import AgentOrchestrator, Event
from core.database import Database
from core.knowledge_engine import KnowledgeEngine
from core.seo_history import SEOHealth, SEOHistory
from core.task_engine import TaskEngine
from core.website_registry import WebsiteRegistry


IGNORED_WEBSITE_STATUSES = {"phasing_out", "archived", "cancelled"}
RECOVERY_SUBPROJECTS = (
    "Analyse",
    "Teknisk SEO",
    "Indhold",
    "Intern linking",
    "CTR-optimering",
    "Evaluering",
)


@dataclass(frozen=True)
class SEOManagerSiteResult:
    """Result of analyzing one eligible website."""

    website: str
    action: str
    reason: str
    project_id: int | None
    health: SEOHealth | None


@dataclass(frozen=True)
class SEOManagerResult:
    """Aggregate status for terminal and dashboard output."""

    websites_analyzed: int
    new_projects: int
    updated_projects: int
    no_action: int
    highest_priority: dict[str, Any] | None


class SEOManager:
    """Analyze SEO health and plan recovery work without editing websites."""

    def __init__(
        self,
        *,
        database: Database,
        seo_history: SEOHistory,
        website_registry: WebsiteRegistry,
        project_manager: ProjectManager,
        task_engine: TaskEngine,
        knowledge_engine: KnowledgeEngine,
        agent_orchestrator: AgentOrchestrator,
    ) -> None:
        shared_databases = {
            id(database),
            id(seo_history.database),
            id(website_registry.database),
            id(project_manager.database),
            id(task_engine.database),
            id(agent_orchestrator.database),
        }
        if len(shared_databases) != 1:
            raise ValueError("SEO Manager-komponenter skal dele database.")
        self.database = database
        self.seo_history = seo_history
        self.website_registry = website_registry
        self.project_manager = project_manager
        self.task_engine = task_engine
        self.knowledge_engine = knowledge_engine
        self.agent_orchestrator = agent_orchestrator

    def analyze_all_sites(
        self,
        analysis_date: date | None = None,
    ) -> SEOManagerResult:
        """Analyze eligible websites and create justified recovery plans."""
        reference_date = analysis_date or date.today()
        analyzed = 0
        created = 0
        updated = 0
        no_action = 0
        for website in self.website_registry.get_all():
            if website["status"] in IGNORED_WEBSITE_STATUSES:
                continue
            result = self.analyze_site(
                website["website"],
                analysis_date=reference_date,
            )
            analyzed += 1
            if result.action == "created":
                created += 1
            elif result.action == "updated":
                updated += 1
            else:
                no_action += 1

        recommendations = [
            item
            for item in self.get_recommendations()
            if item["status"] in {"project_created", "project_updated"}
            and item["analysis_date"] == reference_date.isoformat()
        ]
        return SEOManagerResult(
            websites_analyzed=analyzed,
            new_projects=created,
            updated_projects=updated,
            no_action=no_action,
            highest_priority=recommendations[0] if recommendations else None,
        )

    def analyze_site(
        self,
        website_id: str,
        *,
        analysis_date: date | None = None,
    ) -> SEOManagerSiteResult:
        """Analyze one website using its 28-day SEO Health snapshot."""
        website = self.website_registry.get(website_id)
        if website is None:
            raise ValueError(f"Website findes ikke: {website_id}")
        if website["status"] in IGNORED_WEBSITE_STATUSES:
            return SEOManagerSiteResult(
                website=website_id,
                action="ignored",
                reason=f"Website-status er {website['status']}.",
                project_id=None,
                health=None,
            )

        health = next(
            item
            for item in self.seo_history.analyze_site(
                website_id,
                analysis_date,
            )
            if item.period == "28d"
        )
        reason = self._reason(health)
        analysis_day = (analysis_date or date.today()).isoformat()
        if not self.should_create_project(health):
            self.database.upsert_seo_recommendation(
                website_id=website_id,
                analysis_date=analysis_day,
                seo_score=health.score,
                trend=health.trend,
                reason=reason,
                recommendation="Fortsæt overvågning uden recovery-projekt.",
                priority="low",
                project_id=None,
                status="no_action",
            )
            return SEOManagerSiteResult(
                website=website_id,
                action="no_action",
                reason=reason,
                project_id=None,
                health=health,
            )

        project_id, created = self.create_recovery_project(website_id, health)
        priority = self._priority(health)
        self.database.upsert_seo_recommendation(
            website_id=website_id,
            analysis_date=analysis_day,
            seo_score=health.score,
            trend=health.trend,
            reason=reason,
            recommendation=(
                "Undersøg faldet gennem det oprettede SEO Recovery-projekt."
            ),
            priority=priority,
            project_id=project_id,
            status="project_created" if created else "project_updated",
        )
        if created:
            self.agent_orchestrator.submit_event(
                Event(
                    event_type="seo_recovery_project_created",
                    source="SEO Manager",
                    website=website_id,
                    title=f"SEO Recovery – {website_id}",
                    description=reason,
                    priority=self._priority_score(health),
                    data={
                        "project_id": project_id,
                        "required_capabilities": ["seo", "planning"],
                    },
                )
            )
        return SEOManagerSiteResult(
            website=website_id,
            action="created" if created else "updated",
            reason=reason,
            project_id=project_id,
            health=health,
        )

    def should_create_project(self, health: SEOHealth) -> bool:
        """Return whether documented 28-day deterioration is actionable."""
        clicks = health.click_change_pct
        return any(
            (
                health.score < 35,
                health.trend == "critical",
                clicks is not None and clicks <= -25,
                clicks is not None
                and clicks <= -15
                and health.position_change is not None
                and health.position_change > 0,
                clicks is not None
                and clicks <= -15
                and health.ctr_change is not None
                and health.ctr_change < 0,
            )
        )

    def create_recovery_project(
        self,
        website_id: str,
        health: SEOHealth,
    ) -> tuple[int, bool]:
        """Create or update one idempotent SEO Recovery project and tasks."""
        title = f"SEO Recovery – {website_id}"
        existing = self.database.get_project_by_website_and_title(
            website_id,
            title,
        )
        description = self._project_description(health)
        priority = self._priority(health)
        expected_effect = (
            "Stabilisér organisk synlighed og genvind dokumenterede tab i "
            "klik, CTR eller placering."
        )
        if existing is None:
            project_id = self.project_manager.create_project(
                website_id=website_id,
                title=title,
                description=description,
                priority=priority,
                expected_effect=expected_effect,
            )
            created = True
        else:
            project_id = int(existing["id"])
            self.project_manager.update_project(
                project_id,
                description=description,
                priority=priority,
                expected_effect=expected_effect,
                status="ready",
            )
            created = False

        subproject_ids = self.project_manager.divide_project(
            project_id,
            [
                (
                    title,
                    f"SEO Recovery-arbejde inden for {title.lower()}.",
                )
                for title in RECOVERY_SUBPROJECTS
            ],
        )
        self._ensure_start_tasks(
            website_id,
            project_id,
            dict(zip(RECOVERY_SUBPROJECTS, subproject_ids)),
            health,
        )
        return project_id, created

    def get_recommendations(
        self,
        website_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return persisted SEO Manager recommendations."""
        return self.database.get_seo_recommendations(website_id)

    def _ensure_start_tasks(
        self,
        website_id: str,
        project_id: int,
        subprojects: dict[str, int],
        health: SEOHealth,
    ) -> None:
        existing = {
            task["title"]: task
            for task in self.task_engine.get_tasks_for_project(project_id)
        }
        reason = self._reason(health)
        task_specs = (
            (
                "Analyse",
                "Identificér de ti sider med størst klikfald",
                "Brug Search Console til at rangere sider efter absolut "
                "kliknedgang i den dokumenterede periode.",
                "SEO Manager",
                90,
                "En prioriteret liste over de ti største dokumenterede fald.",
                "Gem klikfald og periode for de ti identificerede sider.",
            ),
            (
                "Analyse",
                "Sammenlign placering, CTR og visninger før og efter faldet",
                "Sammenlign de berørte siders placering, CTR og visninger "
                "mellem de to 28-dagesperioder.",
                "SEO Manager",
                75,
                "Et målbart billede af hvilke SEO-signaler der har ændret sig.",
                "Dokumentér før/efter-tal for alle tre metrikker.",
            ),
            (
                "Teknisk SEO",
                "Kontrollér om faldet rammer enkelte sider eller hele websitet",
                "Fordel klikfaldet på sider og sektioner og kontrollér "
                "tekniske mønstre uden at ændre websitet.",
                "Webmaster",
                60,
                "Afgrænsning af om problemet er lokalt eller site-wide.",
                "Angiv andelen af faldet fra top-10-siderne og øvrige sider.",
            ),
            (
                "Analyse",
                "Formulér en foreløbig hypotese om årsagen",
                "Sammenfat data og SEO-regler i én testbar hypotese. Markér "
                "tydeligt hvad der er fakta, og hvad der er hypotese.",
                "SEO Manager",
                60,
                "En dokumenteret hypotese, der kan be- eller afkræftes.",
                "Gem hypotese, evidens og et konkret falsifikationskriterium.",
            ),
            (
                "Indhold",
                "Vælg den første side, der skal undersøges nærmere",
                "Vælg én side ud fra klikfald, forretningsværdi og styrken af "
                "den foreløbige hypotese. Foretag ingen websiteændring.",
                "Content Manager",
                45,
                "Et begrundet og afgrænset første undersøgelsesobjekt.",
                "Gem valgt URL, baseline og begrundelse for prioriteringen.",
            ),
        )
        dependency: int | None = None
        priority_score = self._priority_score(health)
        for (
            subproject,
            title,
            description,
            agent,
            minutes,
            expected_effect,
            measurement_method,
        ) in task_specs:
            if title in existing:
                dependency = int(existing[title]["id"])
                continue
            task_ids = self.project_manager.create_concrete_task(
                subproject_id=subprojects[subproject],
                website_id=website_id,
                title=title,
                description=description,
                reason=reason,
                assigned_agent=agent,
                estimated_minutes=minutes,
                expected_effect=expected_effect,
                priority_score=priority_score,
                depends_on_task_id=dependency,
                measurement_method=measurement_method,
            )
            dependency = task_ids[-1]

    def _project_description(self, health: SEOHealth) -> str:
        seo_documents = self.knowledge_engine.get_documents_by_category("seo")
        return (
            f"Undersøg dokumenteret SEO-tilbagegang for {health.website}. "
            f"28-dages SEO-score: {health.score:.1f}; trend: {health.trend}. "
            f"Analysen bygger på {len(seo_documents)} SEO-vidensdokumenter."
        )

    @staticmethod
    def _reason(health: SEOHealth) -> str:
        reasons: list[str] = []
        if health.score < 35:
            reasons.append(f"SEO-score er {health.score:.1f}, under 35")
        if health.trend == "critical":
            reasons.append("trenden er critical")
        if health.click_change_pct is not None:
            reasons.append(
                f"klik er ændret {health.click_change_pct:+.1f}%"
            )
        if health.position_change is not None:
            reasons.append(
                f"placering er ændret {health.position_change:+.2f}"
            )
        if health.ctr_change is not None:
            reasons.append(f"CTR er ændret {health.ctr_change:+.2f} point")
        return "; ".join(reasons) or "Utilstrækkeligt sammenligningsgrundlag."

    @staticmethod
    def _priority(health: SEOHealth) -> str:
        if health.trend == "critical" or health.score < 25:
            return "critical"
        if health.score < 35 or (
            health.click_change_pct is not None
            and health.click_change_pct <= -25
        ):
            return "high"
        return "medium"

    @staticmethod
    def _priority_score(health: SEOHealth) -> int:
        return max(1, min(100, round(100 - health.score)))
