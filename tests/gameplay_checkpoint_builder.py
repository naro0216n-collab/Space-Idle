from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

# This is an executable test-harness entry point, so resolve the repository root
# explicitly instead of depending on pytest's import-path setup.
_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(_REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPOSITORY_ROOT))

import test_gameplay_mechanics as gameplay


def _fixture_body(fixture):
    return getattr(fixture, "__wrapped__", fixture)


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")


def _copy_prior(input_dir: Path, output_dir: Path, names: tuple[str, ...]) -> dict[str, dict]:
    states: dict[str, dict] = {}
    for name in names:
        state = _read(input_dir / f"{name}.json")
        states[name] = state
        _write(output_dir / f"{name}.json", state)
    return states


def build_orbital(output_dir: Path) -> None:
    orbital = _fixture_body(gameplay.orbital_research_checkpoint)()
    cislunar = _fixture_body(gameplay.cislunar_checkpoint)(orbital)
    _write(output_dir / "orbital_research.json", orbital)
    _write(output_dir / "cislunar.json", cislunar)


def build_survey(input_dir: Path, output_dir: Path) -> None:
    states = _copy_prior(input_dir, output_dir, ("orbital_research", "cislunar"))
    survey_ready = _fixture_body(gameplay.survey_ready_checkpoint)(states["cislunar"])
    _write(output_dir / "survey_ready.json", survey_ready)


def build_isru(input_dir: Path, output_dir: Path) -> None:
    states = _copy_prior(
        input_dir,
        output_dir,
        ("orbital_research", "cislunar", "survey_ready"),
    )
    isru = _fixture_body(gameplay.isru_checkpoint)(states["survey_ready"])
    _write(output_dir / "isru.json", isru)

    # The checkpoint itself is not enough: verify that the resulting state
    # actually closes the intended research -> survey -> ISRU progression loop.
    gameplay.test_research_survey_and_isru_form_a_playable_dependency_chain_through_application_api(
        isru
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("orbital", "survey", "isru"))
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--input-dir", type=Path)
    args = parser.parse_args()

    if args.stage == "orbital":
        build_orbital(args.output_dir)
    else:
        if args.input_dir is None:
            parser.error(f"{args.stage} stage requires --input-dir")
        if args.stage == "survey":
            build_survey(args.input_dir, args.output_dir)
        else:
            build_isru(args.input_dir, args.output_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
