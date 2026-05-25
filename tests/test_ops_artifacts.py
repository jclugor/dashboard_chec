from pathlib import Path



def test_compose_smoke_script_exists() -> None:
    script = Path(__file__).resolve().parents[1] / "scripts" / "compose_smoke.sh"
    assert script.exists()
    assert script.stat().st_mode & 0o111



def test_ci_workflow_exists() -> None:
    workflow = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "ci.yml"
    assert workflow.exists()
