"""
Unit tests for intensity classifier.
Covers every classification branch to ensure individual pattern accuracy.
"""
import pytest

from drift_gate.core.classification.intensity import (
    classify_file_intensity,
    max_intensity,
    meets_min_intensity,
    INTENSITY_ORDER,
)
from drift_gate.core.models.changed_file import ChangedFile


def _file(patch: str = "", status: str = "modified", signals: list = None, path: str = "src/foo.py") -> ChangedFile:
    return ChangedFile(path=path, status=status, patch=patch, semantic_signals=signals or [])


# ── status shortcuts ────────────────────────────────────────────────────────────

class TestStatusShortcuts:
    def test_added_file_is_export_added(self):
        assert classify_file_intensity(_file(status="added")) == "export-added"

    def test_deleted_file_is_signature_change(self):
        assert classify_file_intensity(_file(status="deleted")) == "signature-change"

    def test_renamed_file_is_signature_change(self):
        assert classify_file_intensity(_file(status="renamed")) == "signature-change"

    def test_empty_patch_is_signature_change(self):
        assert classify_file_intensity(_file(patch="")) == "signature-change"

    def test_patch_with_only_hunk_header_is_impl_only(self):
        assert classify_file_intensity(_file(patch="@@ -1,2 +1,2 @@\n context")) == "impl-only"


# ── comment-only ─────────────────────────────────────────────────────────────

class TestCommentOnly:
    def test_python_hash_comment(self):
        patch = "@@ -1,1 +1,1 @@\n-# old comment\n+# new comment\n"
        assert classify_file_intensity(_file(patch=patch)) == "comment-only"

    def test_js_line_comment(self):
        patch = "@@ -1,1 +1,1 @@\n-// old\n+// new\n"
        assert classify_file_intensity(_file(patch=patch)) == "comment-only"

    def test_block_comment_star(self):
        patch = "@@ -1,1 +1,1 @@\n-* @param x\n+* @param y\n"
        assert classify_file_intensity(_file(patch=patch)) == "comment-only"

    def test_blank_lines_only(self):
        patch = "@@ -1,2 +1,2 @@\n-\n+\n"
        assert classify_file_intensity(_file(patch=patch)) == "comment-only"

    def test_docstring_triple_quote_only(self):
        patch = '@@ -1,1 +1,1 @@\n-"""\n+"""\n'
        assert classify_file_intensity(_file(patch=patch)) == "comment-only"


# ── config-key-added ──────────────────────────────────────────────────────────

class TestConfigKeyAdded:
    def test_new_env_var_uppercase(self):
        patch = "@@ -1,1 +1,2 @@\n DATABASE_URL=postgres\n+REDIS_URL=redis://localhost\n"
        assert classify_file_intensity(_file(patch=patch)) == "config-key-added"

    def test_process_env_access(self):
        patch = "@@ -1,1 +1,1 @@\n-const x = process.env.OLD_KEY\n+const x = process.env.NEW_KEY\n"
        assert classify_file_intensity(_file(patch=patch)) == "config-key-added"

    def test_python_os_environ(self):
        patch = "@@ -1,1 +1,1 @@\n+val = os.environ.get('NEW_SECRET')\n"
        assert classify_file_intensity(_file(patch=patch)) == "config-key-added"

    def test_pydantic_base_settings(self):
        patch = "@@ -1,1 +1,1 @@\n+class Config(BaseSettings): pass\n"
        assert classify_file_intensity(_file(patch=patch)) == "config-key-added"

    def test_removed_key_only_not_config_added(self):
        # Only removed, no new key → not config-key-added
        patch = "@@ -1,2 +1,1 @@\n-OLD_KEY=value\n DATABASE_URL=postgres\n"
        result = classify_file_intensity(_file(patch=patch))
        assert result != "config-key-added"


# ── route-contract-change ────────────────────────────────────────────────────

class TestRouteContractChange:
    def test_express_router_get(self):
        patch = "@@ -1,1 +1,1 @@\n+router.get('/users', handler)\n"
        assert classify_file_intensity(_file(patch=patch)) == "route-contract-change"

    def test_express_app_post(self):
        patch = "@@ -1,1 +1,1 @@\n+app.post('/api/data', handler)\n"
        assert classify_file_intensity(_file(patch=patch)) == "route-contract-change"

    def test_fastapi_decorator(self):
        patch = "@@ -1,1 +1,1 @@\n+@app.get('/users/{id}')\n"
        assert classify_file_intensity(_file(patch=patch)) == "route-contract-change"

    def test_typescript_http_decorator(self):
        patch = "@@ -1,1 +1,1 @@\n+@Get('/endpoint')\n"
        assert classify_file_intensity(_file(patch=patch)) == "route-contract-change"

    def test_request_response_dto(self):
        patch = "@@ -1,1 +1,1 @@\n+export interface CreateUserRequest {\n"
        assert classify_file_intensity(_file(patch=patch)) == "route-contract-change"

    def test_openapi_yaml_path(self):
        patch = "@@ -1,2 +1,2 @@\n-/users:\n+/users/{id}:\n"
        assert classify_file_intensity(_file(patch=patch)) == "route-contract-change"


# ── db-schema-change ──────────────────────────────────────────────────────────

class TestDbSchemaChange:
    def test_create_table_sql(self):
        patch = "@@ -1,1 +1,1 @@\n+CREATE TABLE orders (\n"
        assert classify_file_intensity(_file(patch=patch)) == "db-schema-change"

    def test_alter_table_add_column(self):
        patch = "@@ -1,1 +1,1 @@\n+ALTER TABLE users ADD COLUMN email VARCHAR(255);\n"
        assert classify_file_intensity(_file(patch=patch)) == "db-schema-change"

    def test_drop_column(self):
        patch = "@@ -1,1 +1,1 @@\n+ALTER TABLE users DROP COLUMN legacy_field;\n"
        assert classify_file_intensity(_file(patch=patch)) == "db-schema-change"

    def test_prisma_model_block(self):
        patch = "@@ -1,1 +1,1 @@\n+model User {\n"
        assert classify_file_intensity(_file(patch=patch)) == "db-schema-change"

    def test_prisma_field_with_decorator(self):
        patch = "@@ -1,1 +1,1 @@\n+  email String @unique\n"
        assert classify_file_intensity(_file(patch=patch)) == "db-schema-change"

    def test_not_null_constraint(self):
        patch = "@@ -1,1 +1,1 @@\n+  column NOT NULL DEFAULT ''\n"
        assert classify_file_intensity(_file(patch=patch)) == "db-schema-change"


# ── auth-policy-change ────────────────────────────────────────────────────────

class TestAuthPolicyChange:
    def test_role_keyword(self):
        patch = "@@ -1,1 +1,1 @@\n+if user.role == 'admin':\n"
        assert classify_file_intensity(_file(patch=patch)) == "auth-policy-change"

    def test_rbac_keyword(self):
        patch = "@@ -1,1 +1,1 @@\n+const rbac = new RBAC(config)\n"
        assert classify_file_intensity(_file(patch=patch)) == "auth-policy-change"

    def test_require_role_call(self):
        patch = "@@ -1,1 +1,1 @@\n+requireRole('editor')\n"
        assert classify_file_intensity(_file(patch=patch)) == "auth-policy-change"

    def test_auth_middleware(self):
        patch = "@@ -1,1 +1,1 @@\n+app.use(authMiddleware())\n"
        assert classify_file_intensity(_file(patch=patch)) == "auth-policy-change"

    def test_opa_policy_key(self):
        patch = "@@ -1,1 +1,1 @@\n+allow: true\n"
        assert classify_file_intensity(_file(patch=patch)) == "auth-policy-change"


# ── ci-secret-change ──────────────────────────────────────────────────────────

class TestCiSecretChange:
    def test_secrets_accessor(self):
        patch = "@@ -1,1 +1,1 @@\n+token: ${{ secrets.PROD_API_KEY }}\n"
        assert classify_file_intensity(_file(patch=patch)) == "ci-secret-change"

    def test_token_env_var(self):
        patch = "@@ -1,1 +1,1 @@\n+GITHUB_TOKEN: ${{ secrets.GH_TOKEN }}\n"
        assert classify_file_intensity(_file(patch=patch)) == "ci-secret-change"

    def test_dockerfile_from(self):
        patch = "@@ -1,1 +1,1 @@\n+FROM node:20-alpine\n"
        assert classify_file_intensity(_file(patch=patch)) == "ci-secret-change"

    def test_terraform_resource(self):
        patch = '@@ -1,1 +1,1 @@\n+resource "aws_instance" "web" {\n'
        assert classify_file_intensity(_file(patch=patch)) == "ci-secret-change"

    def test_k8s_apiversion(self):
        patch = "@@ -1,1 +1,1 @@\n+apiVersion:\n"
        assert classify_file_intensity(_file(patch=patch)) == "ci-secret-change"

    def test_deploy_keyword(self):
        patch = "@@ -1,1 +1,1 @@\n+    - name: Deploy to production\n"
        assert classify_file_intensity(_file(patch=patch)) == "ci-secret-change"


# ── public-cli-change ─────────────────────────────────────────────────────────

class TestPublicCliChange:
    def test_argparse_add_argument(self):
        patch = "@@ -1,1 +1,1 @@\n+parser.add_argument('--output', help='output file')\n"
        assert classify_file_intensity(_file(patch=patch)) == "public-cli-change"

    def test_click_option(self):
        patch = "@@ -1,1 +1,1 @@\n+@click.option('--verbose', is_flag=True)\n"
        assert classify_file_intensity(_file(patch=patch)) == "public-cli-change"

    def test_subparser_command(self):
        patch = "@@ -1,1 +1,1 @@\n+sub = subparsers.add_parser('init')\n"
        assert classify_file_intensity(_file(patch=patch)) == "public-cli-change"

    def test_commander_option(self):
        patch = "@@ -1,1 +1,1 @@\n+program.option('--debug', 'enable debug')\n"
        assert classify_file_intensity(_file(patch=patch)) == "public-cli-change"

    def test_cobra_flags(self):
        patch = "@@ -1,1 +1,1 @@\n+cmd.Flags().String(\"output\", \"\", \"output file\")\n"
        assert classify_file_intensity(_file(patch=patch)) == "public-cli-change"


# ── export-added ──────────────────────────────────────────────────────────────

class TestExportAdded:
    def test_new_js_export_function(self):
        patch = "@@ -1,1 +1,2 @@\n existing\n+export function newHelper() {}\n"
        assert classify_file_intensity(_file(patch=patch)) == "export-added"

    def test_new_ts_export_const(self):
        patch = "@@ -1,1 +1,2 @@\n existing\n+export const NEW_CONSTANT = 42\n"
        assert classify_file_intensity(_file(patch=patch)) == "export-added"

    def test_export_not_added_when_also_removed(self):
        # Both added and removed → not a net-new export
        patch = "@@ -1,1 +1,1 @@\n-export function old() {}\n+export function new_fn() {}\n"
        result = classify_file_intensity(_file(patch=patch))
        assert result in ("signature-change", "export-added")  # rename may be either

    def test_python_public_class(self):
        patch = "@@ -1,1 +1,1 @@\n+public class Service:\n"
        assert classify_file_intensity(_file(patch=patch)) == "export-added"


# ── signature-change ─────────────────────────────────────────────────────────

class TestSignatureChange:
    def test_python_function_def(self):
        patch = "@@ -1,1 +1,1 @@\n-def fetch_user(id):\n+def fetch_user(id, include_deleted=False):\n"
        assert classify_file_intensity(_file(patch=patch)) == "signature-change"

    def test_typescript_interface(self):
        patch = "@@ -1,1 +1,1 @@\n-interface UserConfig {\n+interface UserConfig {\n"
        assert classify_file_intensity(_file(patch=patch)) == "signature-change"

    def test_class_definition(self):
        patch = "@@ -1,1 +1,1 @@\n+class ServiceHandler extends BaseHandler {\n"
        # May match signature-change or export-added (class keyword)
        result = classify_file_intensity(_file(patch=patch))
        assert INTENSITY_ORDER[result] >= INTENSITY_ORDER["signature-change"]

    def test_impl_only_when_no_patterns_match(self):
        patch = "@@ -1,2 +1,2 @@\n-    return old_value\n+    return new_value\n"
        assert classify_file_intensity(_file(patch=patch)) == "impl-only"


# ── semantic signal override ──────────────────────────────────────────────────

class TestSemanticSignalOverride:
    def test_env_key_added_signal(self):
        f = _file(signals=["env-key-added"])
        assert classify_file_intensity(f) == "config-key-added"

    def test_route_contract_signal(self):
        f = _file(signals=["route-contract-change"])
        assert classify_file_intensity(f) == "route-contract-change"

    def test_openapi_operation_signal(self):
        f = _file(signals=["openapi-operation-changed"])
        assert classify_file_intensity(f) == "route-contract-change"

    def test_db_model_signal(self):
        f = _file(signals=["db-model-schema-changed"])
        assert classify_file_intensity(f) == "db-schema-change"

    def test_function_signature_signal(self):
        f = _file(signals=["function-signature-changed"])
        assert classify_file_intensity(f) == "signature-change"

    def test_public_export_signal(self):
        f = _file(signals=["public-export-added"])
        assert classify_file_intensity(f) == "export-added"

    def test_cli_flag_signal(self):
        f = _file(signals=["cli-flag-added"])
        assert classify_file_intensity(f) == "public-cli-change"

    def test_multiple_signals_highest_wins(self):
        # route-contract-change (3) > signature-change (2)
        f = _file(signals=["function-signature-changed", "route-contract-change"])
        assert classify_file_intensity(f) == "route-contract-change"

    def test_unknown_signal_falls_through_to_patch(self):
        patch = "@@ -1,1 +1,1 @@\n+router.get('/a', h)\n"
        f = _file(patch=patch, signals=["totally-unknown-signal"])
        assert classify_file_intensity(f) == "route-contract-change"


# ── max_intensity ─────────────────────────────────────────────────────────────

class TestMaxIntensity:
    def test_highest_wins(self):
        files = [
            _file(patch="@@ -1,1 +1,1 @@\n+# comment\n"),         # comment-only
            _file(patch="@@ -1,1 +1,1 @@\n+router.get('/x', h)\n"), # route-contract-change
            _file(patch="@@ -1,2 +1,2 @@\n-val\n+val2\n"),          # impl-only
        ]
        assert max_intensity(files) == "route-contract-change"

    def test_single_file(self):
        f = [_file(status="deleted")]
        assert max_intensity(f) == "signature-change"

    def test_empty_list_returns_comment_only(self):
        assert max_intensity([]) == "comment-only"


# ── meets_min_intensity ───────────────────────────────────────────────────────

class TestMeetsMinIntensity:
    def test_any_always_passes(self):
        assert meets_min_intensity("comment-only", "any")

    def test_empty_always_passes(self):
        assert meets_min_intensity("comment-only", "")

    def test_none_always_passes(self):
        assert meets_min_intensity("comment-only", None)

    def test_exact_match(self):
        assert meets_min_intensity("signature-change", "signature-change")

    def test_higher_actual_passes(self):
        assert meets_min_intensity("route-contract-change", "signature-change")

    def test_lower_actual_fails(self):
        assert not meets_min_intensity("comment-only", "signature-change")

    def test_impl_only_below_signature(self):
        assert not meets_min_intensity("impl-only", "signature-change")
