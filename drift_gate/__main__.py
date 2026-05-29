"""Module entrypoint for `python -m drift_gate` and `py -m drift_gate`."""
from drift_gate.adapters.cli.runner import run_cli


if __name__ == "__main__":
    run_cli()
