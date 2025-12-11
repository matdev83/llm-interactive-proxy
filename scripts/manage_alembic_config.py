import subprocess

def manage_alembic_config(alembic_args: list[str]) -> None:
    """
    Manages alembic.ini configuration and then executes alembic command.

    Checks for alembic.ini, if not found, copies from alembic.example.ini.
    Then, executes the alembic command with the provided arguments.
    """
    project_root = Path(__file__).resolve().parents[1]
    alembic_ini_path = project_root / "alembic.ini"
    alembic_example_ini_path = project_root / "alembic.example.ini"

    if not alembic_ini_path.exists():
        if alembic_example_ini_path.exists():
            print(f"INFO: alembic.ini not found. Copying from {alembic_example_ini_path}")
            shutil.copy(alembic_example_ini_path, alembic_ini_path)
        else:
            print(f"ERROR: alembic.ini not found and alembic.example.ini is also missing at {alembic_example_ini_path}.")
            print("Please create an alembic.ini file or provide an alembic.example.ini template.")
            sys.exit(1)

    # Reconstruct the command to execute alembic
    # Using sys.executable to ensure the correct Python interpreter (from .venv) is used
    # and then -m alembic to run alembic as a module.
    command = [sys.executable, "-m", "alembic"] + alembic_args
    
    print(f"Executing command: {' '.join(command)}")
    # Execute the alembic command
    result = subprocess.run(command, env=os.environ.copy(), check=False)

    if result.returncode != 0:
        print(f"ERROR: Alembic command failed with exit code {result.returncode}")
        sys.exit(result.returncode)

if __name__ == "__main__":
    # Remove the script name itself from arguments and pass the rest to alembic
    alembic_command_args = sys.argv[1:]
    
    if not alembic_command_args:
        print("Usage: python manage_alembic_config.py [alembic_command] [args...]")
        print("Example: python manage_alembic_config.py upgrade head")
        sys.exit(1)

    manage_alembic_config(alembic_command_args)
