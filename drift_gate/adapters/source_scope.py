"""Declared product paths for repository self-check (not a runtime detector)."""
def product_path(path):
    return ((path.startswith('drift_gate/') and not path.startswith('drift_gate/tests/'))
        or path.startswith(('desktop-ui/src/', 'packaging/', '.github/workflows/'))
        or path in {'main.py', 'pyproject.toml', 'action.yml', '.drift-gate.self.yml',
                    'scripts/check_self.py', 'desktop-ui/package.json',
                    'desktop-ui/package-lock.json', 'desktop-ui/vite.config.ts'})
