"""Dockerfile and .env files are classified wherever they sit in the repository,
and glob brackets stay literal so framework paths such as app/[slug]/page.tsx match themselves."""
import pytest

from drift_gate.core.classification.classifier import get_file_change_types
from drift_gate.utils.glob_matcher import match_glob


@pytest.mark.parametrize('path', ['Dockerfile', 'Dockerfile.dev', 'docker/Dockerfile', 'services/api/Dockerfile.prod'])
def test_dockerfiles_are_workflow_ci_at_any_depth(path):
    assert 'workflow-ci' in get_file_change_types(path)


@pytest.mark.parametrize('path', ['.env', '.env.local', 'apps/web/.env', 'services/api/.env.production'])
def test_env_files_are_env_config_at_any_depth(path):
    assert 'env-config' in get_file_change_types(path)


@pytest.mark.parametrize('path', ['src/dockerfile_notes.py', 'src/environment.py', 'docs/dockerfile-guide.md'])
def test_similar_names_are_not_misclassified(path):
    types = get_file_change_types(path)
    assert 'workflow-ci' not in types and 'env-config' not in types


def test_brackets_in_a_pattern_are_literal_characters():
    assert match_glob('app/[slug]/page.tsx', 'app/[slug]/page.tsx')
    assert not match_glob('app/s/page.tsx', 'app/[slug]/page.tsx')
