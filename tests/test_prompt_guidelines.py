import unittest

from core.prompt_guidelines import PromptGuidelines
from core.task_deliverables import _prompt


class FakeDatabase:
    def __init__(self):
        self.states = {}

    def get_integration_state(self, key):
        return self.states.get(key)

    def set_integration_state(self, key, value):
        self.states[key] = value


class PromptGuidelinesTests(unittest.TestCase):
    def test_global_and_task_guidelines_are_combined(self):
        database = FakeDatabase()
        service = PromptGuidelines(database)
        service.save(
            "Brug aldrig priser.",
            {
                "title_meta": "Undgå formuleringen Få overblik over.",
                "internal_links": "Ankerteksten skal passe naturligt.",
            },
        )

        text = service.text_for("title_meta")

        self.assertIn("Brug aldrig priser.", text)
        self.assertIn("Undgå formuleringen Få overblik over.", text)
        self.assertNotIn("Ankerteksten skal passe naturligt.", text)

    def test_empty_task_guideline_is_removed(self):
        database = FakeDatabase()
        service = PromptGuidelines(database)

        service.save("", {"title_meta": "", "unknown": "Ignoreres"})

        self.assertEqual({"global": "", "tasks": {}}, service.get())

    def test_non_dictionary_database_value_is_treated_as_empty(self):
        database = FakeDatabase()
        database.states["prompt_guidelines"] = object()

        self.assertEqual(
            {"global": "", "tasks": {}},
            PromptGuidelines(database).get(),
        )

    def test_guidelines_are_added_to_work_draft_prompt(self):
        prompt = _prompt(
            {
                "title": "Opdatér siden",
                "description": "Lav et konkret forslag.",
                "target_url": "https://example.dk/side/",
                "_prompt_guidelines": (
                    "Overordnede retningslinjer:\nSkriv naturligt dansk."
                ),
            },
            [],
        )

        self.assertIn("BRUGERADMINISTREREDE RETNINGSLINJER", prompt)
        self.assertIn("Skriv naturligt dansk.", prompt)


if __name__ == "__main__":
    unittest.main()
