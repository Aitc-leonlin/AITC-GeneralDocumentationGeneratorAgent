import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.features.membership.repositories.rbac_repository import RbacRepository
from src.features.membership.seeds.default_seed_data import ROOT_ORG_ID, SUPER_ADMIN_ROLE_ID, SYSTEM_ADMIN_USER_ID
from src.features.membership.services.auth_service import AuthService
from src.features.membership.services.bootstrap_service import ensure_membership_infrastructure
from src.features.membership.services.notification_service import NotificationAdminService
from src.features.membership.services.user_service import UserManagementService


OUTPUT_PATH = PROJECT_ROOT / "output" / "phase8_test_results.json"


def record(results: list[dict[str, Any]], name: str, status: str, details: dict[str, Any] | None = None) -> None:
    results.append({"name": name, "status": status, "details": details or {}})


def main() -> None:
    results: list[dict[str, Any]] = []
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    try:
        bootstrap = ensure_membership_infrastructure()
        record(results, "seed_data_and_migrations", "passed", bootstrap)
    except Exception as exc:
        record(results, "seed_data_and_migrations", "failed", {"error": str(exc)})
        write_results(results)
        raise

    admin_service = NotificationAdminService()
    auth_service = AuthService()
    user_service = UserManagementService()
    rbac_repository = RbacRepository()

    try:
        dashboard = admin_service.admin_dashboard()
        required_keys = {"userStats", "permissionOverview", "loginStats", "notificationStats", "recentAuditLogs"}
        record(
            results,
            "admin_dashboard",
            "passed" if required_keys.issubset(dashboard.keys()) else "failed",
            {"keys": sorted(dashboard.keys())},
        )
    except Exception as exc:
        record(results, "admin_dashboard", "failed", {"error": str(exc)})

    try:
        templates = admin_service.list_templates()
        template_codes = {template["code"] for template in templates}
        expected_codes = {
            "AUTH_PASSWORD_RESET",
            "AUTH_EMAIL_VERIFICATION",
            "RBAC_PERMISSION_CHANGED",
            "MEMBERSHIP_ACCOUNT_LOCKED",
            "AUTH_LOGIN_ANOMALY",
        }
        record(
            results,
            "email_notification_templates",
            "passed" if expected_codes.issubset(template_codes) else "failed",
            {"templateCodes": sorted(template_codes)},
        )
    except Exception as exc:
        record(results, "email_notification_templates", "failed", {"error": str(exc)})

    try:
        auth_service.forgot_password(
            email="system.admin@example.local",
            ip_address="127.0.0.1",
            user_agent="phase8-smoke-test",
        )
        outbox = admin_service.list_outbox(
            status="",
            template_code="AUTH_PASSWORD_RESET",
            page=1,
            page_size=5,
        )
        record(
            results,
            "password_reset_notification",
            "passed" if outbox["total"] > 0 else "failed",
            {"total": outbox["total"]},
        )
    except Exception as exc:
        record(results, "password_reset_notification", "failed", {"error": str(exc)})

    try:
        user_service.lock_user(SYSTEM_ADMIN_USER_ID)
        user_service.unlock_user(SYSTEM_ADMIN_USER_ID)
        outbox = admin_service.list_outbox(
            status="",
            template_code="MEMBERSHIP_ACCOUNT_LOCKED",
            page=1,
            page_size=5,
        )
        record(
            results,
            "account_locked_notification",
            "passed" if outbox["total"] > 0 else "failed",
            {"total": outbox["total"]},
        )
    except Exception as exc:
        record(results, "account_locked_notification", "failed", {"error": str(exc)})

    try:
        auth_service.repository.record_failed_login(
            user_id=SYSTEM_ADMIN_USER_ID,
            failed_count=1,
            locked_until=None,
            ip_address="127.0.0.1",
            user_agent="phase8-smoke-test",
        )
        outbox = admin_service.list_outbox(
            status="",
            template_code="AUTH_LOGIN_ANOMALY",
            page=1,
            page_size=5,
        )
        record(
            results,
            "login_anomaly_notification",
            "passed" if outbox["total"] > 0 else "failed",
            {"total": outbox["total"]},
        )
    except Exception as exc:
        record(results, "login_anomaly_notification", "failed", {"error": str(exc)})

    try:
        rbac_repository.set_user_roles(SYSTEM_ADMIN_USER_ID, [SUPER_ADMIN_ROLE_ID], ROOT_ORG_ID)
        outbox = admin_service.list_outbox(
            status="",
            template_code="RBAC_PERMISSION_CHANGED",
            page=1,
            page_size=5,
        )
        record(
            results,
            "permission_changed_notification",
            "passed" if outbox["total"] > 0 else "failed",
            {"total": outbox["total"]},
        )
    except Exception as exc:
        record(results, "permission_changed_notification", "failed", {"error": str(exc)})

    try:
        audit_logs = admin_service.list_audit_logs(
            page=1,
            page_size=5,
            action="auth.login.failed",
            resource_type="",
            outcome="",
        )
        record(
            results,
            "audit_log_query",
            "passed" if audit_logs["total"] > 0 else "failed",
            {"total": audit_logs["total"]},
        )
    except Exception as exc:
        record(results, "audit_log_query", "failed", {"error": str(exc)})

    try:
        pending = admin_service.list_outbox(status="PENDING", template_code="", page=1, page_size=1)
        if pending["items"]:
            dispatched = admin_service.dispatch_outbox(pending["items"][0]["id"], {"status": "SENT"})
            record(results, "notification_dispatch_api", "passed", {"status": dispatched["status"]})
        else:
            record(results, "notification_dispatch_api", "skipped", {"reason": "no pending outbox item"})
    except Exception as exc:
        record(results, "notification_dispatch_api", "failed", {"error": str(exc)})

    record(results, "e2e_test", "skipped", {"reason": "no existing E2E test configuration found for membership admin"})
    write_results(results)


def write_results(results: list[dict[str, Any]]) -> None:
    summary = {
        "phase": 8,
        "scope": "Notification, Admin Dashboard, Integration Smoke Test",
        "results": results,
        "summary": {
            "passed": sum(1 for item in results if item["status"] == "passed"),
            "failed": sum(1 for item in results if item["status"] == "failed"),
            "skipped": sum(1 for item in results if item["status"] == "skipped"),
        },
    }
    OUTPUT_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
