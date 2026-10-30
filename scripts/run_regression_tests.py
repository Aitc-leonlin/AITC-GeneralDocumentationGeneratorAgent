#!/usr/bin/env python3
"""Run backend regression checks against a temporary SQLite database copy.

The tests intentionally avoid successful chatbot/report generation calls because
those paths may invoke an external or local LLM. They focus on API contracts,
auth, shared provider configuration, and CRUD behavior that should remain stable.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
import unittest
from collections import defaultdict
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = PROJECT_ROOT / "FinancialStatementXBRL.db"
TEST_DB_PATH: Path | None = None


def configure_environment(test_db_path: Path) -> None:
    os.environ["SQLITE_DB_PATH"] = str(test_db_path)
    os.environ.setdefault("LLM_PROVIDER", "local")
    os.environ.setdefault("LOCAL_LLM_BASE_URL", "http://127.0.0.1:9/v1")
    os.environ.setdefault("LOCAL_LLM_MODEL_NAME", "regression-test-model")
    os.environ.setdefault("LOCAL_LLM_API_KEY", "not-needed")


def prepare_test_database() -> Path:
    source_db = Path(os.getenv("REGRESSION_SOURCE_DB_PATH", str(DEFAULT_DB_PATH))).resolve()
    if not source_db.exists():
        raise FileNotFoundError(
            f"Regression source DB not found: {source_db}. "
            "Set REGRESSION_SOURCE_DB_PATH to a valid SQLite DB."
        )

    temp_dir = Path(tempfile.mkdtemp(prefix="aitc-regression-"))
    test_db_path = temp_dir / source_db.name
    shutil.copy2(source_db, test_db_path)
    return test_db_path


def import_app():
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    from app import app

    return app


def route_inventory(app: Any) -> dict[str, list[str]]:
    inventory: dict[str, list[str]] = defaultdict(list)
    for route in app.routes:
        methods = sorted(method for method in getattr(route, "methods", []) if method not in {"HEAD", "OPTIONS"})
        path = getattr(route, "path", "")
        tags = getattr(route, "tags", None) or ["untagged"]
        if not methods or not path.startswith("/api/"):
            continue
        inventory[", ".join(tags)].append(f"{','.join(methods):<11} {path}")
    return dict(sorted(inventory.items()))


def print_route_inventory(app: Any) -> None:
    print("\nCurrent API feature inventory:")
    for tag, routes in route_inventory(app).items():
        print(f"\n[{tag}]")
        for route in sorted(routes):
            print(f"  {route}")
    print()


class BackendRegressionTests(unittest.TestCase):
    client = None
    token = ""

    @classmethod
    def setUpClass(cls) -> None:
        from fastapi.testclient import TestClient

        app = import_app()
        cls.client = TestClient(app)
        login_response = cls.client.post(
            "/api/membership/auth/login",
            json={
                "login": "system.admin",
                "password": "Admin123!",
                "rememberMe": False,
            },
        )
        assert login_response.status_code == 200, login_response.text
        payload = login_response.json()
        assert payload.get("success") is True, payload
        cls.token = payload["data"]["accessToken"]

    @property
    def auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}

    def assert_standard_success(self, response: Any) -> dict[str, Any]:
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertIs(payload.get("success"), True, payload)
        self.assertIsNone(payload.get("error"), payload)
        return payload

    def test_route_inventory_covers_current_feature_groups(self) -> None:
        app = import_app()
        tags = route_inventory(app)
        expected_tags = {
            "chatbot",
            "expert-knowledge",
            "membership-admin",
            "membership-auth",
            "membership-menus",
            "membership-organizations",
            "membership-rbac",
            "membership-system",
            "membership-users",
            "report-generator",
            "warehouse-data",
        }
        self.assertTrue(expected_tags.issubset(set(tags)), sorted(tags))

    def test_openapi_contract_is_available(self) -> None:
        response = self.client.get("/openapi.json")
        self.assertEqual(response.status_code, 200, response.text)
        paths = response.json().get("paths", {})
        for path in [
            "/api/chatbot",
            "/api/chatbot-with-external",
            "/api/expert-knowledge",
            "/api/warehouse-data",
            "/api/membership/auth/login",
            "/api/report-generator/history",
        ]:
            self.assertIn(path, paths)

    def test_protected_chatbot_endpoint_rejects_missing_auth_before_llm(self) -> None:
        response = self.client.post(
            "/api/chatbot",
            json={
                "messages": [{"role": "user", "content": "hello"}],
                "question": "hello",
                "company": "",
                "period": "",
                "show_intermediate_steps": False,
            },
        )
        self.assertEqual(response.status_code, 401, response.text)

    def test_membership_auth_and_current_user_contract(self) -> None:
        response = self.client.get("/api/membership/auth/me", headers=self.auth_headers)
        payload = self.assert_standard_success(response)
        self.assertEqual(payload["data"]["username"], "system.admin")
        self.assertIn("email", payload["data"])

    def test_membership_read_endpoints_contract(self) -> None:
        endpoints = [
            "/api/membership/rbac/me/permissions",
            "/api/membership/rbac/roles",
            "/api/membership/rbac/permission-groups",
            "/api/membership/rbac/permissions",
            "/api/membership/menus/current",
            "/api/membership/users?page=1&pageSize=5",
        ]
        for endpoint in endpoints:
            with self.subTest(endpoint=endpoint):
                self.assert_standard_success(self.client.get(endpoint, headers=self.auth_headers))

    def test_report_history_contract(self) -> None:
        response = self.client.get(
            "/api/report-generator/history?page=1&pageSize=5&offset=0",
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertIn("reports", payload)
        self.assertIn("total", payload)
        self.assertIn("page", payload)
        self.assertIn("pageSize", payload)

    def test_warehouse_data_crud_contract(self) -> None:
        entry_id = "regression-warehouse-data"
        self.client.delete(f"/api/warehouse-data/{entry_id}", headers=self.auth_headers)
        payload = {
            "id": entry_id,
            "category": "regression",
            "title": "Regression Warehouse Data",
            "industry": "Semiconductor",
            "companyLabel": "Regression Co",
            "companyPromptValue": "9999",
            "summary": "Regression test summary.",
            "source": "regression-test",
            "url": "https://example.local/warehouse",
        }

        create_response = self.client.post("/api/warehouse-data", json=payload, headers=self.auth_headers)
        self.assertEqual(create_response.status_code, 201, create_response.text)
        created = create_response.json()
        self.assertEqual(created["id"], entry_id)
        self.assertEqual(created["title"], payload["title"])

        get_response = self.client.get(f"/api/warehouse-data/{entry_id}", headers=self.auth_headers)
        self.assertEqual(get_response.status_code, 200, get_response.text)
        self.assertEqual(get_response.json()["category"], "regression")

        list_response = self.client.get(
            "/api/warehouse-data?page=1&pageSize=10&keyword=Regression%20Warehouse",
            headers=self.auth_headers,
        )
        self.assertEqual(list_response.status_code, 200, list_response.text)
        self.assertGreaterEqual(list_response.json()["total"], 1)

        updated_payload = {**payload, "title": "Regression Warehouse Data Updated"}
        update_response = self.client.put(
            f"/api/warehouse-data/{entry_id}",
            json=updated_payload,
            headers=self.auth_headers,
        )
        self.assertEqual(update_response.status_code, 200, update_response.text)
        self.assertEqual(update_response.json()["title"], updated_payload["title"])

        delete_response = self.client.delete(f"/api/warehouse-data/{entry_id}", headers=self.auth_headers)
        self.assertEqual(delete_response.status_code, 204, delete_response.text)

        missing_response = self.client.get(f"/api/warehouse-data/{entry_id}", headers=self.auth_headers)
        self.assertEqual(missing_response.status_code, 404, missing_response.text)

    def test_expert_knowledge_crud_contract(self) -> None:
        entry_id = "regression-expert-knowledge"
        self.client.delete(f"/api/expert-knowledge/{entry_id}", headers=self.auth_headers)
        payload = {
            "id": entry_id,
            "title": "Regression Expert Knowledge",
            "dataSource": "財務報表",
            "industry": "Semiconductor",
            "companyLabel": "Regression Co",
            "companyPromptValue": "9999",
            "sourceSchemaKey": "",
            "anchorDescription": "Regression anchor description.",
            "systemPrompt": "Regression system prompt.",
        }

        create_response = self.client.post("/api/expert-knowledge", json=payload, headers=self.auth_headers)
        self.assertEqual(create_response.status_code, 201, create_response.text)
        created = create_response.json()
        self.assertEqual(created["id"], entry_id)
        self.assertTrue(created["sourceSchemaKey"].startswith("expert_knowledge."))

        applied_response = self.client.get(
            "/api/expert-knowledge/applied"
            "?companyLabel=Regression%20Co&companyPromptValue=9999"
            "&industry=Semiconductor&dataSource=%E8%B2%A1%E5%8B%99%E5%A0%B1%E8%A1%A8",
            headers=self.auth_headers,
        )
        self.assertEqual(applied_response.status_code, 200, applied_response.text)
        self.assertTrue(any(entry["id"] == entry_id for entry in applied_response.json()))

        updated_payload = {**payload, "title": "Regression Expert Knowledge Updated"}
        update_response = self.client.put(
            f"/api/expert-knowledge/{entry_id}",
            json=updated_payload,
            headers=self.auth_headers,
        )
        self.assertEqual(update_response.status_code, 200, update_response.text)
        self.assertEqual(update_response.json()["title"], updated_payload["title"])

        delete_response = self.client.delete(f"/api/expert-knowledge/{entry_id}", headers=self.auth_headers)
        self.assertEqual(delete_response.status_code, 204, delete_response.text)

        missing_response = self.client.get(f"/api/expert-knowledge/{entry_id}", headers=self.auth_headers)
        self.assertEqual(missing_response.status_code, 404, missing_response.text)

    def test_local_llm_provider_url_normalization(self) -> None:
        from src.features.chatbot.core.providers.chat_openAI_provider import normalize_openai_base_url

        self.assertEqual(
            normalize_openai_base_url("http://192.168.20.169:8004/v1/chat/completions"),
            "http://192.168.20.169:8004/v1",
        )
        self.assertEqual(
            normalize_openai_base_url("http://192.168.20.169:8004/v1/"),
            "http://192.168.20.169:8004/v1",
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run AITC backend regression tests.")
    parser.add_argument(
        "--list-only",
        action="store_true",
        help="Print current API feature inventory without running tests.",
    )
    return parser.parse_args()


def main() -> int:
    global TEST_DB_PATH
    args = parse_args()
    TEST_DB_PATH = prepare_test_database()
    configure_environment(TEST_DB_PATH)
    app = import_app()
    print_route_inventory(app)

    if args.list_only:
        return 0

    suite = unittest.defaultTestLoader.loadTestsFromTestCase(BackendRegressionTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
