import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


def manage_alembic_config(alembic_args: list[str]) -> None:
    """

    Manages alembic.ini configuration and then executes alembic command.



    Checks for alembic.ini, if not found, copies from alembic.example.ini.

    Then, executes the alembic command with the provided arguments.

    """

    parser = argparse.ArgumentParser(
        description="Manage Alembic configuration and run commands."
    )

    parser.add_argument(
        "--project-root", type=str, help="Explicitly set the project root directory."
    )

    # Parse just the known arguments for manage_alembic_config, leaving alembic_args untouched

    # We need to create a dummy argparse.Namespace here to avoid parsing alembic_args as well

    known_args, remaining_alembic_args = parser.parse_known_args(alembic_args)

    if known_args.project_root:

        project_root = Path(known_args.project_root).resolve()

    else:

        project_root = Path(__file__).resolve().parents[1]

    alembic_ini_path = project_root / "alembic.ini"

    alembic_example_ini_path = project_root / "alembic.example.ini"

    should_run_alembic = False

    if not alembic_ini_path.exists():

        if alembic_example_ini_path.exists():

            print(
                f"INFO: alembic.ini not found. Copying from {alembic_example_ini_path}",
                flush=True,
            )

            try:

                shutil.copy(alembic_example_ini_path, alembic_ini_path)

                should_run_alembic = True

            except Exception as e:

                print(f"ERROR: Failed to copy alembic.example.ini: {e}", flush=True)

                sys.exit(1)

        else:

            print(
                f"ERROR: Alembic configuration files missing. Expected: {alembic_ini_path} or {alembic_example_ini_path}",
                flush=True,
            )

            print(
                "Please create an alembic.ini file or provide an alembic.example.ini template.",
                flush=True,
            )

            sys.exit(1)

    else:

        should_run_alembic = True

    if should_run_alembic:

        # Reconstruct the command to execute alembic

        # Using sys.executable to ensure the correct Python interpreter (from .venv) is used

        # and then -m alembic to run alembic as a module.

        command = [sys.executable, "-m", "alembic", *remaining_alembic_args]

        print(f"Executing command: {' '.join(command)}", flush=True)

        # Execute the alembic command

        result = subprocess.run(
            command, capture_output=True, text=True, check=False, env=os.environ.copy()
        )

        if result.stdout:

            print(result.stdout, end="", flush=True)

        if result.stderr:

            print(result.stderr, end="", flush=True)

        if result.returncode != 0:

            print(
                f"ERROR: Alembic command failed with exit code {result.returncode}",
                flush=True,
            )

            sys.exit(result.returncode)


if __name__ == "__main__":

    # Remove the script name itself from arguments and pass the rest to alembic

    # argparse will handle splitting known args from alembic_args internally.

    manage_alembic_config(sys.argv[1:])
