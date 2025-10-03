import os


def test_no_python_files_in_root_except_setup():
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    root_files = os.listdir(root_dir)
    python_files = [
        f
        for f in root_files
        if f.endswith(".py") and os.path.isfile(os.path.join(root_dir, f))
    ]
    assert "setup.py" in python_files
    python_files.remove("setup.py")
    assert (
        len(python_files) == 0
    ), f"Found development artifacts (temporary Python files) in root: {python_files}"


def test_no_md_files_in_root_except_important():
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    root_files = os.listdir(root_dir)
    md_files = [
        f
        for f in root_files
        if f.endswith(".md") and os.path.isfile(os.path.join(root_dir, f))
    ]
    important_md = ["README.md", "AGENTS.md", "CONTRIBUTING.md", "CHANGELOG.md"]
    additional_allowed_md = [
        "CLAUDE.md",
        "GEMINI.md",
        "MEMORY.md",
        "QWEN.md",
        "TEST.md",
    ]

    for f in important_md:
        assert f in md_files, f"Expected {f} to be in root but not found"
        md_files.remove(f)

    md_files = [f for f in md_files if f not in additional_allowed_md]

    assert (
        len(md_files) == 0
    ), f"Found development artifacts (temporary *.md files) in root: {md_files}"


def test_no_log_files_in_root():
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    root_files = os.listdir(root_dir)
    log_files = [
        f
        for f in root_files
        if f.endswith(".log") and os.path.isfile(os.path.join(root_dir, f))
    ]
    assert (
        len(log_files) == 0
    ), f"Found development artifacts (*.log files) in root: {log_files}"


def test_no_txt_files_in_root():
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    root_files = os.listdir(root_dir)
    txt_files = [
        f
        for f in root_files
        if f.endswith(".txt") and os.path.isfile(os.path.join(root_dir, f))
    ]
    assert (
        len(txt_files) == 0
    ), f"Found development artifacts (*.txt files) in root: {txt_files}"
