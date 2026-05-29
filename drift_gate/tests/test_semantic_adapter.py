from drift_gate.adapters.ast import TREE_SITTER_AVAILABLE
from drift_gate.adapters.ast.analyzer import enrich_semantic_signals
from drift_gate.adapters.ast.tree_sitter_support import parse_sexp
from drift_gate.core.models.changed_file import ChangedFile


def test_typescript_route_signal_from_patch():
    files = [
        ChangedFile(
            path="src/routes/users.ts",
            status="modified",
            patch="+router.post('/users', createUser)\n",
        )
    ]

    enriched = enrich_semantic_signals(files)

    assert enriched[0].semantic_signals == ["route-contract-change"]
    assert "TS/JS route handler changed" in enriched[0].semantic_evidence


def test_tree_sitter_grammar_is_available():
    assert TREE_SITTER_AVAILABLE is True
    assert "function_definition" in parse_sexp("python", ["def create_user():", "    pass"])
    assert "function_declaration" in parse_sexp(
        "typescript", ["export function createUser(id: string) {}"]
    )
    assert "function_declaration" in parse_sexp("go", ["func CreateUser(id string) {}"])


def test_python_route_signal_from_patch():
    files = [
        ChangedFile(
            path="app/main.py",
            status="modified",
            patch="+@app.post('/users')\n+def create_user():\n",
        )
    ]

    enriched = enrich_semantic_signals(files)

    assert "route-contract-change" in enriched[0].semantic_signals
    assert "function-signature-changed" in enriched[0].semantic_signals


def test_python_cli_signal_from_patch():
    files = [ChangedFile(
        path="main.py",
        status="modified",
        patch=(
            "diff --git a/main.py b/main.py\n"
            "@@ -1 +1,2 @@\n"
            " parser = argparse.ArgumentParser()\n"
            "+parser.add_argument('--json', action='store_true')\n"
        ),
    )]

    enriched = enrich_semantic_signals(files)

    assert "public-cli-change" in enriched[0].semantic_signals


def test_typescript_schema_signal_from_patch():
    files = [ChangedFile(
        path="src/routes/users.ts",
        status="modified",
        patch=(
            "diff --git a/src/routes/users.ts b/src/routes/users.ts\n"
            "@@ -1 +1 @@\n"
            "+const CreateUserRequest = z.object({ email: z.string() })\n"
        ),
    )]

    enriched = enrich_semantic_signals(files)

    assert "route-contract-change" in enriched[0].semantic_signals


def test_config_schema_signal_from_patch():
    files = [ChangedFile(
        path="src/config/settings.py",
        status="modified",
        patch=(
            "diff --git a/src/config/settings.py b/src/config/settings.py\n"
            "@@ -1 +1 @@\n"
            "+class Settings(BaseSettings):\n"
        ),
    )]

    enriched = enrich_semantic_signals(files)

    assert "env-key-added" in enriched[0].semantic_signals


def test_sdk_public_contract_signal_from_patch():
    files = [ChangedFile(
        path="sdk/users.ts",
        status="modified",
        patch=(
            "diff --git a/sdk/users.ts b/sdk/users.ts\n"
            "@@ -1 +1 @@\n"
            "+export function getUser(id: string) {}\n"
        ),
    )]

    enriched = enrich_semantic_signals(files)

    assert "route-contract-change" in enriched[0].semantic_signals


def test_go_java_kotlin_ruby_semantic_signals():
    files = [
        ChangedFile(
            path="internal/api/user.go",
            status="modified",
            patch="@@ -1 +1 @@\n+type UserResponse struct { ID string }\n",
        ),
        ChangedFile(
            path="src/main/java/UserController.java",
            status="modified",
            patch="@@ -1 +1 @@\n+public class UserController {}\n",
        ),
        ChangedFile(
            path="app/models/user.rb",
            status="modified",
            patch="@@ -1 +1 @@\n+def public_name\n",
        ),
    ]

    enriched = enrich_semantic_signals(files)

    assert "class-interface-type-changed" in enriched[0].semantic_signals
    assert "class-interface-type-changed" in enriched[1].semantic_signals
    assert "function-signature-changed" in enriched[2].semantic_signals


def test_openapi_and_db_model_semantic_signals():
    files = [
        ChangedFile(
            path="openapi/users.yml",
            status="modified",
            patch="@@ -1 +1 @@\n+operationId: createUser\n",
        ),
        ChangedFile(
            path="prisma/schema.prisma",
            status="modified",
            patch="@@ -1 +1 @@\n+model User { id String @id }\n",
        ),
    ]

    enriched = enrich_semantic_signals(files)

    assert "openapi-operation-changed" in enriched[0].semantic_signals
    assert "db-model-schema-changed" in enriched[1].semantic_signals
