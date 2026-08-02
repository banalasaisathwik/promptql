pass

import unittest

from fastapi.testclient import TestClient

from app.connectors.fixture_catalog import FIXTURE_SCENARIOS, MERGE_READY_REQUEST
from app.main import app


class PullRequestInspectionApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(app)

    def test_catalog_returns_every_backend_scenario_in_order(self) -> None:
        response = self.client.get("/v1/demo/pull-request-scenarios")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(len(body["items"]), len(FIXTURE_SCENARIOS))
        self.assertEqual(
            [item["id"] for item in body["items"]],
            [scenario.id for scenario in FIXTURE_SCENARIOS],
        )
        self.assertEqual(body["items"][0]["request"], MERGE_READY_REQUEST.model_dump())

    def test_inspection_returns_combined_github_and_jira_facts(self) -> None:
        request_body = MERGE_READY_REQUEST.model_dump()

        response = self.client.post(
            "/v1/pull-request-inspections",
            json=request_body,
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["request"], request_body)
        self.assertEqual(body["github"]["state"], "open")
        self.assertFalse(body["github"]["is_draft"])
        self.assertEqual(body["github"]["linked_jira_key"], "ENG-101")
        self.assertEqual(body["jira"]["issue_key"], "ENG-101")
        self.assertEqual(body["jira"]["status"], "done")

    def test_unknown_valid_request_returns_typed_not_found_error(self) -> None:
        response = self.client.post(
            "/v1/pull-request-inspections",
            json={
                "repository_owner": "acme",
                "repository_name": "analytics",
                "pr_number": 404,
            },
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            response.json(),
            {
                "code": "fixture_not_found",
                "message": "No connector fixture exists for this pull request.",
            },
        )

    def test_invalid_request_returns_validation_error(self) -> None:
        response = self.client.post(
            "/v1/pull-request-inspections",
            json={
                "repository_owner": "acme",
                "repository_name": "analytics",
                "pr_number": 0,
            },
        )

        self.assertEqual(response.status_code, 422)

    def test_identical_requests_return_identical_http_responses(self) -> None:
        request_body = MERGE_READY_REQUEST.model_dump()

        first = self.client.post("/v1/pull-request-inspections", json=request_body)
        second = self.client.post("/v1/pull-request-inspections", json=request_body)

        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json(), second.json())


if __name__ == "__main__":
    unittest.main()
