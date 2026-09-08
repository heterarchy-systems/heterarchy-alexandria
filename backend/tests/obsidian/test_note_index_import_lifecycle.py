"""Native indexing loads at use, while application imports remain effect free."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def test_application_import_defers_native_loading_until_note_indexing(
    tmp_path: Path,
) -> None:
    environment = os.environ.copy()
    environment["HETERARCHY_ALEXANDRIA_NATIVE_LIBRARY"] = str(tmp_path / "missing.so")
    environment["SERVICE_GRAPH_READ_MODEL"] = "postgresql"
    environment["PYTHONPYCACHEPREFIX"] = str(tmp_path / "pycache")
    note = tmp_path / "note.md"
    note.write_text("---\nid: import-test\nalexandria_type: context\n---\n# Test\n")
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys\n"
            "from pathlib import Path\n"
            "import app.main\n"
            "assert 'heterarchy_alexandria_native' not in sys.modules\n"
            "from app.obsidian.application.notes.obsidian_note_indexer import note_index_from_path\n"
            "try:\n"
            "    note_index_from_path(Path(sys.argv[1]), 'note.md', '.')\n"
            "except RuntimeError as error:\n"
            "    assert 'NATIVE_COMPUTE_UNAVAILABLE' in str(error)\n"
            "else:\n"
            "    raise AssertionError('Indexing must require native compute')\n",
            str(note),
        ],
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
