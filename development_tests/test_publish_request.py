from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from development_tests.script_harness import (
    commit_all, git, load_script, read_content_tree_plan, run_script, write_source_snapshot,
)

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "publish_request.py"
PUBLISH_REQUEST = load_script(SCRIPT, "space_idle_test_publish_request")


def run_request(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return run_script(PUBLISH_REQUEST, SCRIPT, repo, *args, check=check)


def transaction(repo: Path) -> Path:
    return repo / ".git" / "space-idle-publish-transaction"


def manifest_path(repo: Path) -> Path:
    return transaction(repo) / "manifest.json"


def connector_state(repo: Path) -> dict[str, object]:
    return json.loads((transaction(repo) / "connector" / "connector-state.json").read_text(encoding="utf-8"))


def prepared(repo: Path) -> dict[str, object]:
    return json.loads(manifest_path(repo).read_text(encoding="utf-8"))


def init_repo(tmp_path: Path) -> tuple[Path, str, str, str, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init")
    (repo / "payload.txt").write_text("base\n", encoding="utf-8")
    commit_all(repo, "base")
    git(repo, "branch", "-M", "develop")
    base = git(repo, "rev-parse", "HEAD")
    base_tree = git(repo, "rev-parse", "HEAD^{tree}")
    snapshot = write_source_snapshot(repo, tmp_path / "source-snapshot")
    git(repo, "remote", "add", "origin", str((snapshot / "repository.bundle").resolve()))
    result = json.loads(run_request(repo, "init").stdout)
    assert result["publish_commit"] == base
    assert result["publish_tree"] == base_tree
    return repo, base, base_tree, base, base_tree


def prepare_change(repo: Path, text: str = "changed\n") -> dict[str, object]:
    (repo / "payload.txt").write_text(text, encoding="utf-8")
    commit_all(repo, "checkpoint")
    return json.loads(run_request(repo, "prepare").stdout)


def plan(repo: Path, develop_head: str, publish_head: str) -> dict[str, object]:
    return json.loads(run_request(
        repo, "connector-plan",
        "--develop-head", develop_head,
        "--publish-head", publish_head,
    ).stdout)


def test_init_requires_exact_develop_and_publish_base_metadata(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init")
    (repo / "x").write_text("x\n", encoding="utf-8")
    commit_all(repo, "base")
    git(repo, "branch", "-M", "develop")
    snapshot = write_source_snapshot(repo, tmp_path / "source-snapshot")
    git(repo, "remote", "add", "origin", str((snapshot / "repository.bundle").resolve()))
    ok = json.loads(run_request(repo, "init").stdout)
    assert ok["remote_commit"] == git(repo, "rev-parse", "HEAD")
    assert ok["publish_commit"] == git(repo, "rev-parse", "refs/space-idle/publish-base")
    assert git(repo, "config", "--local", "--get", "user.name") == PUBLISH_REQUEST.PUBLISH_IDENTITY_NAME
    assert git(repo, "config", "--local", "--get", "user.email") == PUBLISH_REQUEST.PUBLISH_IDENTITY_EMAIL

    (snapshot / ".source-publish-tree").write_text("f" * 40 + "\n", encoding="utf-8")
    broken = run_request(repo, "init", check=False)
    assert broken.returncode != 0
    assert "publish base" in broken.stderr



def test_init_restores_publish_base_after_clone_from_snapshot_bundle(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    git(source, "init")
    (source / "x").write_text("x\n", encoding="utf-8")
    commit_all(source, "base")
    git(source, "branch", "-M", "develop")
    snapshot = write_source_snapshot(source, tmp_path / "source-snapshot")

    restored = tmp_path / "restored"
    subprocess.run(
        ["git", "clone", "-b", "develop", str(snapshot / "repository.bundle"), str(restored)],
        check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    assert subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", "refs/space-idle/publish-base"],
        cwd=restored, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    ).returncode != 0

    result = json.loads(run_request(restored, "init").stdout)
    assert result["publish_commit"] == git(restored, "rev-parse", "refs/space-idle/publish-base")
    assert result["publish_commit"] == (snapshot / ".source-publish-commit").read_text(encoding="utf-8").strip()


def test_prepare_uses_head_only_and_excludes_uncommitted_work(tmp_path: Path) -> None:
    repo, _, _, _, _ = init_repo(tmp_path)
    (repo / "payload.txt").write_text("checkpoint\n", encoding="utf-8")
    commit_all(repo, "checkpoint")
    checkpoint = git(repo, "rev-parse", "HEAD")
    checkpoint_tree = git(repo, "rev-parse", "HEAD^{tree}")
    (repo / "payload.txt").write_text("uncommitted\n", encoding="utf-8")
    result = json.loads(run_request(repo, "prepare").stdout)
    request = prepared(repo)
    assert result["local_target_commit"] == checkpoint
    assert result["target_tree"] == checkpoint_tree
    assert result["working_tree_clean"] is False
    assert request["version"] == 8
    # The published identity and timestamp must belong to the committed target,
    # not to later working-tree edits.
    assert git(repo, "show", "-s", "--format=%cI", str(result["publish_commit"])) == git(
        repo, "show", "-s", "--format=%cI", checkpoint
    )
    raw = subprocess.run(
        ["git", "cat-file", "commit", str(request["publish_commit"])], cwd=repo,
        check=True, stdout=subprocess.PIPE,
    ).stdout
    assert raw.partition(b"\n\n")[2] == b"checkpoint\n"


def test_connector_plan_uses_tree_content_batches_and_scales_past_single_call_budget(tmp_path: Path) -> None:
    repo, base, _, publish_head, _ = init_repo(tmp_path)
    (repo / "large.bin").write_bytes(os.urandom(420_000))
    commit_all(repo, "large checkpoint")
    run_request(repo, "prepare")
    summary = plan(repo, base, publish_head)

    assert summary["strategy"] == "fixed-slot-16kib-tree-content-batches"
    assert summary["transport_chunk_bytes"] == 16 * 1024
    assert summary["payload_part_count"] > 8
    assert summary["tree_call_count"] > 1
    assert summary["normal_pre_ref_helper_round_trips"] == 0

    state = connector_state(repo)
    assert state["stage"] == "execution-plan-ready"
    plan_data = state["plan"]
    assert isinstance(plan_data, dict)
    chunks = plan_data["chunks"]
    assert isinstance(chunks, list) and len(chunks) == summary["payload_part_count"]
    assert all(len(str(chunk["content"]).encode("utf-8")) <= 16 * 1024 for chunk in chunks)

    expected_paths = {str(chunk["path"]) for chunk in chunks}
    observed_paths: set[str] = set()
    tree_packets = summary["tree_packets"]
    assert len(tree_packets) == summary["tree_call_count"]
    final_tree, packets = read_content_tree_plan(tree_packets, state["publish_base_tree"])
    for index, packet in enumerate(packets):
        assert packet["tree_batch_index"] == index
        encoded_args = json.dumps(
            packet["action_args"], ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
        assert len(encoded_args) <= 144 * 1024
        for entry in packet["action_args"]["tree_elements"]:
            if str(entry["path"]).endswith(".b64"):
                assert "content" in entry
                assert "sha" not in entry
                observed_paths.add(str(entry["path"]))

    assert observed_paths == expected_paths
    assert final_tree == plan_data["final_tree"]

    commit_packet = json.loads(Path(str(summary["commit_packet"])).read_text(encoding="utf-8"))
    assert commit_packet["action"] == "GitHub.create_commit"
    assert commit_packet["action_args"]["tree_sha"] == plan_data["final_tree"]
    assert commit_packet["action_args"]["parent_sha"] == publish_head
    assert summary["post_commit_ref_update"] == {
        "action": "GitHub.update_ref",
        "repository_full_name": PUBLISH_REQUEST.GITHUB_REPOSITORY,
        "branch_name": "publish",
        "sha": "<GitHub.create_commit returned SHA>",
        "force": False,
    }


def test_record_uses_prepared_identity_without_reverifying_bundle_and_tracks_gateway_run(tmp_path: Path) -> None:
    repo, base, _, publish_head, _ = init_repo(tmp_path)
    result = prepare_change(repo)
    summary = plan(repo, base, publish_head)
    candidate = "a" * 40
    # Work on the next checkpoint must not change the prepared transaction.
    (repo / "later.txt").write_text("later\n", encoding="utf-8")
    commit_all(repo, "later local work")

    recorded = json.loads(run_request(
        repo, "record",
        "--gateway-transport-commit", candidate,
        "--gateway-run-id", "12345",
        "--gateway-conclusion", "success",
    ).stdout)
    assert recorded["verified"] is True
    assert recorded["record_verification"] == "manifest-identity-and-gateway-run"
    assert recorded["remote_commit"] == result["publish_commit"]
    assert recorded["local_head"] == result["local_target_commit"]
    assert recorded["local_head"] != git(repo, "rev-parse", "HEAD")
    assert recorded["publish_commit"] == candidate
    assert recorded["publish_tree"] == connector_state_from_summary_tree(summary)
    assert not transaction(repo).exists()


def connector_state_from_summary_tree(summary: dict[str, object]) -> str:
    expected = summary["tree_expected_shas"]
    assert isinstance(expected, list) and expected
    return str(expected[-1])


def test_preflight_and_record_reject_moved_heads_or_modified_manifest(tmp_path: Path) -> None:
    repo, base, _, publish_head, _ = init_repo(tmp_path)
    prepare_change(repo)
    for develop_head, gateway_head in (("c" * 40, publish_head), (base, "d" * 40)):
        rejected = run_request(
            repo, "connector-plan", "--develop-head", develop_head,
            "--publish-head", gateway_head, check=False,
        )
        assert rejected.returncode != 0

    plan(repo, base, publish_head)
    manifest = prepared(repo)
    manifest["request_id"] = "0" * 32
    manifest_path(repo).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    rejected = run_request(
        repo, "record", "--gateway-transport-commit", "c" * 40,
        "--gateway-run-id", "77", "--gateway-conclusion", "success", check=False,
    )
    assert rejected.returncode != 0
    assert "manifest changed" in rejected.stderr


def test_cancel_uses_heads_only_and_never_needs_publish_tree_read(tmp_path: Path) -> None:
    repo, base, _, publish_head, _ = init_repo(tmp_path)
    prepare_change(repo)
    plan(repo, base, publish_head)
    cancelled = json.loads(run_request(
        repo, "cancel",
        "--develop-head", base,
        "--publish-head", publish_head,
    ).stdout)
    assert cancelled["cancelled"] is True
    assert not transaction(repo).exists()


def test_standard_prepare_accepts_only_the_trusted_gateway_workflow_change(tmp_path: Path) -> None:
    repo, _, _, _, _ = init_repo(tmp_path)
    workflow = repo / ".github" / "workflows" / "ci.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text("name: CI\n", encoding="utf-8")
    commit_all(repo, "change workflow")
    blocked = run_request(repo, "prepare", check=False)
    assert blocked.returncode != 0
    assert "workflow_maintenance.py prepare" in blocked.stderr

    git(repo, "reset", "--hard", "HEAD^")
    gateway = repo / ".github" / "workflows" / "publish-gateway.yml"
    gateway.parent.mkdir(parents=True, exist_ok=True)
    gateway.write_text("name: Publish Gateway\n", encoding="utf-8")
    commit_all(repo, "change trusted gateway workflow")
    assert json.loads(run_request(repo, "prepare").stdout)["verified"] is True

def test_gateway_trusted_workflow_guard_requires_publish_control_blob_identity(tmp_path: Path) -> None:
    validator = ROOT / "scripts" / "publish_gateway_validate.py"
    repo = tmp_path / "guard-repo"
    repo.mkdir()
    git(repo, "init")
    gateway = repo / ".github" / "workflows" / "publish-gateway.yml"
    gateway.parent.mkdir(parents=True)
    gateway.write_text("name: old\n", encoding="utf-8")
    commit_all(repo, "base")
    base = git(repo, "rev-parse", "HEAD")
    gateway.write_text("name: trusted\n", encoding="utf-8")
    commit_all(repo, "publish control")
    control = git(repo, "rev-parse", "HEAD")
    (repo / "payload.txt").write_text("source\n", encoding="utf-8")
    commit_all(repo, "target")
    target = git(repo, "rev-parse", "HEAD")
    env = {**os.environ, "BASE_SHA": base, "PUBLISH_COMMIT": target, "GITHUB_SHA": control}
    ok = subprocess.run(["python", str(validator), "--verify-trusted-workflow"], cwd=repo, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert ok.returncode == 0, ok.stderr
    ci = repo / ".github" / "workflows" / "ci.yml"
    ci.write_text("name: untrusted\n", encoding="utf-8")
    commit_all(repo, "untrusted workflow")
    blocked = subprocess.run(
        ["python", str(validator), "--verify-trusted-workflow"], cwd=repo,
        env={**env, "PUBLISH_COMMIT": git(repo, "rev-parse", "HEAD")},
        text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    assert blocked.returncode != 0
    assert "untrusted workflow change" in blocked.stderr


@pytest.mark.skipif(shutil.which("bash") is None, reason="Gateway's bash execution contract is verified on Linux CI")
def test_gateway_workflow_accepts_only_transport_slot_mutations(tmp_path: Path) -> None:
    """Execute the actual Gateway path filter, rather than assert source fragments."""
    workflow = (ROOT / ".github" / "workflows" / "publish-gateway.yml").read_text(encoding="utf-8")
    step = workflow.split("      - name: Resolve fixed transport slot\n", 1)[1]
    script = step.split("        run: |\n", 1)[1].split("      - name:", 1)[0]
    script = "\n".join(line.removeprefix("          ") for line in script.splitlines())

    repo = tmp_path / "gateway"
    repo.mkdir()
    git(repo, "init")
    (repo / "base.txt").write_text("baseline", encoding="utf-8")
    commit_all(repo, "base")

    def run_filter(path: str) -> subprocess.CompletedProcess[str]:
        file = repo / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text("payload", encoding="utf-8")
        commit_all(repo, "candidate transport")
        env_file = tmp_path / "gateway.env"
        env_file.write_text("", encoding="utf-8")
        return subprocess.run(
            ["bash", "-c", script], cwd=repo,
            env={**os.environ, "GITHUB_SHA": git(repo, "rev-parse", "HEAD"),
                 "GITHUB_ENV": str(env_file)},
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )

    accepted = run_filter(".publish/transport/develop/0000.b64")
    assert accepted.returncode == 0, accepted.stderr
    assert "TARGET_BRANCH=develop" in (tmp_path / "gateway.env").read_text(encoding="utf-8")

    for unexpected_path in ("src/unrelated.py", ".publish/transport/publish/0000.b64"):
        rejected = run_filter(unexpected_path)
        assert rejected.returncode != 0


def test_gateway_contract_validates_fixed_slot_then_publishes_exact_commit() -> None:
    workflow = (ROOT / ".github" / "workflows" / "publish-gateway.yml").read_text(encoding="utf-8")
    assert "'.publish/transport/**'" in workflow
    assert "TRANSPORT_DIR=.publish/transport/${branches[0]}" in workflow
    assert "python scripts/publish_gateway_validate.py" in workflow
    assert 'git push origin "${PUBLISH_COMMIT}:refs/heads/${TARGET_BRANCH}"' in workflow
    assert "actions/workflows/ci.yml/dispatches" in workflow
    assert '-f ref="${TARGET_BRANCH}"' in workflow


def test_emitted_tool_calls_preserve_active_packets_and_reject_modified_inputs(tmp_path: Path) -> None:
    repo, base, _, publish_head, _ = init_repo(tmp_path)
    prepare_change(repo)
    summary = plan(repo, base, publish_head)
    packet_dir = transaction(repo) / "connector"
    for stage, packet_name in (("tree", "tree-batch-000.json"), ("commit", "create-transport-commit.json")):
        packet_path = packet_dir / packet_name
        packet = json.loads(packet_path.read_text(encoding="utf-8"))
        generated = run_request(repo, "emit-tool-call", "--stage", stage).stdout
        args_line = next(line for line in generated.splitlines() if line.startswith("const args = "))
        args = json.loads(args_line[len("const args = "):-1])
        assert args == packet["action_args"]
        compact = json.dumps(args, ensure_ascii=False, separators=(",", ":"))
        assert f"serialized.length !== {len(compact)}" in generated
        assert f"0x{PUBLISH_REQUEST._tool_call_fingerprint(compact):08x}" in generated
        if stage == "tree":
            assert packet["expected_tree"] == summary["tree_expected_shas"][0]
            assert f'result.result.sha !== "{packet["expected_tree"]}"' in generated
            assert "tools.mcp__GitHub__create_tree(args)" in generated
        else:
            assert "tools.mcp__GitHub__create_commit(args)" in generated
            assert "tools.mcp__GitHub__update_ref(" in generated
            assert "force:false" in generated
        packet["action_args"]["repository_full_name"] = "untrusted/modified"
        packet_path.write_text(json.dumps(packet), encoding="utf-8")
        rejected = run_request(repo, "emit-tool-call", "--stage", stage, check=False)
        assert rejected.returncode != 0
        assert "packet no longer matches" in rejected.stderr
        packet["action_args"]["repository_full_name"] = PUBLISH_REQUEST.GITHUB_REPOSITORY
        packet_path.write_text(json.dumps(packet), encoding="utf-8")

    rejected = run_request(repo, "emit-tool-call", "--stage", "tree", "--index", "-1", check=False)
    assert rejected.returncode != 0


def _execute_emitted_call(source: str, expected_trees: list[str]) -> subprocess.CompletedProcess[str]:
    """Execute the printed Connector source with mock tools, never writing to GitHub."""
    js = """
const fs = require('node:fs');
const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;
const source = fs.readFileSync(0, 'utf8');
const expectedTrees = JSON.parse(process.argv[1]);
const actions = [];
const tools = {
  mcp__GitHub__create_tree: async (args) => {
    actions.push({kind:'tree', args});
    return {result: {sha: expectedTrees[actions.filter(a => a.kind === 'tree').length - 1]}};
  },
  mcp__GitHub__create_commit: async (args) => {
    actions.push({kind:'commit', args});
    return {result: {sha:'a'.repeat(40)}};
  },
  mcp__GitHub__update_ref: async (args) => {
    actions.push({kind:'ref', args});
    return {result: {success:true}};
  },
};
new AsyncFunction('tools', 'text', source)(tools, () => {})
  .then(() => process.stdout.write(JSON.stringify(actions)))
  .catch(e => { console.error(e.message); process.exitCode = 1; });
"""
    return subprocess.run(
        ["node", "-e", js, json.dumps(expected_trees)], input=source,
        capture_output=True, text=True,
    )


def test_complete_tool_call_uses_original_arguments_and_checks_all_before_writes(tmp_path: Path) -> None:
    repo, base, _, publish_head, _ = init_repo(tmp_path)
    prepare_change(repo)
    summary = plan(repo, base, publish_head)
    expected_trees = summary["tree_expected_shas"]
    original_packets = [json.loads(Path(file).read_text(encoding="utf-8"))
                        for file in summary["tree_packets"]]
    original_commit = json.loads(Path(summary["commit_packet"]).read_text(encoding="utf-8"))
    emitted = run_request(repo, "emit-tool-call").stdout
    assert emitted == run_request(repo, "emit-tool-call", "--stage", "all").stdout
    assert emitted.count("mcp__GitHub__create_tree(") == 1
    assert "mcp__GitHub__create_commit(" in emitted
    assert "mcp__GitHub__update_ref(" in emitted
    completed = _execute_emitted_call(emitted, expected_trees)
    assert completed.returncode == 0, completed.stderr
    actions = json.loads(completed.stdout)
    assert [action["kind"] for action in actions] == ["tree"] * len(original_packets) + ["commit", "ref"]
    assert [action["args"] for action in actions[:-2]] == [p["action_args"] for p in original_packets]
    assert actions[-2]["args"] == original_commit["action_args"]
    assert actions[-1]["args"]["sha"] == "a" * 40
    assert actions[-1]["args"]["force"] is False

    # Mutation in a later packet is caught before the first tree write.
    additional_tree = dict(original_packets[0])
    two_tree_source = PUBLISH_REQUEST._render_complete_tool_call([
        original_packets[0], additional_tree, original_commit
    ])
    broken = two_tree_source.replace(
        '"naro0216n-collab/Space-Idle"', '"naro0216n-collab/Space-Idlf"', 1
    )
    failed = _execute_emitted_call(broken, expected_trees * 2)
    assert failed.returncode != 0
    assert "transfer mismatch" in failed.stderr
    assert failed.stdout == ""  # no GitHub write was reached

    # Source-file alteration is rejected independently of transfer checksum.
    packet_file = Path(summary["commit_packet"])
    altered = json.loads(packet_file.read_text(encoding="utf-8"))
    altered["action_args"]["message"] += "modified"
    packet_file.write_text(json.dumps(altered), encoding="utf-8")
    rejected = run_request(repo, "emit-tool-call", check=False)
    assert rejected.returncode != 0
    assert "packet no longer matches" in rejected.stderr


def test_complete_tool_call_rejects_oversized_script_without_partial_output(tmp_path: Path) -> None:
    repo, base, _, publish_head, _ = init_repo(tmp_path)
    (repo / "large.bin").write_bytes(os.urandom(420_000))
    commit_all(repo, "large checkpoint")
    run_request(repo, "prepare")
    summary = plan(repo, base, publish_head)
    assert summary["tree_call_count"] > 1
    rejected = run_request(repo, "emit-tool-call", check=False)
    assert rejected.returncode != 0
    assert rejected.stdout == ""
    assert "single-call budget" in rejected.stderr
    assert "--stage tree" in rejected.stderr
    assert "mcp__GitHub__create_tree" in run_request(
        repo, "emit-tool-call", "--stage", "tree", "--index", "0"
    ).stdout


def _execute_file_handoff_call(source: str, handoff: Path, mode: str = "normal") -> subprocess.CompletedProcess[str]:
    """Exercise the complete short-source protocol against fake Files and GitHub tools."""
    js = r"""
const fs = require('node:fs');
const AsyncFunction = Object.getPrototypeOf(async function(){}).constructor;
const source = fs.readFileSync(0,'utf8');
const canonical = fs.readFileSync(process.argv[1],'utf8');
const mode = process.argv[2];
const packet = JSON.parse(canonical);
let reads = 0;
let observed = [];
const tools = {
  files__manage_library: async ({operations}) => {
    const op=operations[0]; observed.push(op.operation);
    if (op.operation==='upload') return {results:[{status:'succeeded',file_id:'file-test',library_file_id:'lib-test'}]};
    if (op.operation==='delete') return {results:[{status:'succeeded',message:'File moved to trash.'}]};
    throw Error('unexpected Files operation');
  },
  files__read: async () => {
    observed.push('read'); reads++;
    if (mode==='unreadable' || reads===1) return {results:[{warnings:['not visible'],content:['not visible']}]};
    const data=mode==='tampered'?canonical.replace('GitHub.create_commit','GitHub.creatf_commit'):canonical;
    return {results:[{warnings:[],content:[data],has_more:false}]};
  },
  mcp__GitHub__create_tree: async (args) => {
    observed.push('tree');
    return {result:{sha:packet.packets[observed.filter(x=>x==='tree').length-1].expected_tree}};
  },
  mcp__GitHub__create_commit: async () => {
    observed.push('commit'); return {result:{sha:'a'.repeat(40)}};
  },
  mcp__GitHub__update_ref: async ({sha,force,branch_name}) => {
    observed.push('ref');
    if (sha!=='a'.repeat(40) || force!==false || branch_name!=='publish') throw Error('unsafe ref');
    return {result:{success:true}};
  },
};
new AsyncFunction('tools','text',source)(tools,()=>{})
  .then(()=>process.stdout.write(JSON.stringify(observed)))
  .catch(e=>{process.stdout.write(JSON.stringify(observed));console.error(e.message);process.exitCode=1});
"""
    return subprocess.run(
        ["node", "-e", js, str(handoff), mode], input=source, text=True,
        capture_output=True,
    )


def test_temporary_file_handoff_preserves_verified_packets_and_cleans_up_before_writes(tmp_path: Path) -> None:
    repo, base, _, publish_head, _ = init_repo(tmp_path)
    prepare_change(repo)
    summary = plan(repo, base, publish_head)
    meta = json.loads(run_request(repo, "emit-handoff").stdout)
    data = Path(meta["handoff"]).read_bytes()
    assert len(data) == meta["size"]
    assert json.loads(data)["packets"] == [
        json.loads(Path(path).read_text(encoding="utf-8"))
        for path in [*summary["tree_packets"], summary["commit_packet"]]
    ]
    assert meta == json.loads(run_request(repo, "emit-handoff").stdout)
    source = run_request(repo, "emit-handoff", "--tool-call").stdout
    assert len(source) < 6000  # independent of the transported payload size
    assert "files__manage_library" in source and "files__read" in source
    assert "mcp__GitHub__create_tree" in source and "mcp__GitHub__update_ref" in source
    ok = _execute_file_handoff_call(source, Path(meta["handoff"]))
    assert ok.returncode == 0, ok.stderr
    assert json.loads(ok.stdout) == ["upload", "read", "read", "delete", "tree", "commit", "ref"]

    broken = _execute_file_handoff_call(source, Path(meta["handoff"]), mode="tampered")
    assert broken.returncode != 0
    assert json.loads(broken.stdout) == ["upload", "read", "read", "delete"]
    assert "content mismatch" in broken.stderr
    unreadable = _execute_file_handoff_call(source, Path(meta["handoff"]), mode="unreadable")
    assert unreadable.returncode != 0
    assert json.loads(unreadable.stdout)[-1] == "delete"
    assert "unreadable or truncated" in unreadable.stderr

    packet_file = Path(summary["tree_packets"][0])
    packet = json.loads(packet_file.read_text(encoding="utf-8"))
    packet["action_args"]["repository_full_name"] = "different/repository"
    packet_file.write_text(json.dumps(packet), encoding="utf-8")
    rejected = run_request(repo, "emit-handoff", check=False)
    assert rejected.returncode != 0
    assert "packet no longer matches" in rejected.stderr


def test_temporary_file_handoff_rejects_oversized_transfer(tmp_path: Path) -> None:
    repo, base, _, publish_head, _ = init_repo(tmp_path)
    (repo / "large.bin").write_bytes(os.urandom(420_000))
    commit_all(repo, "large checkpoint")
    run_request(repo, "prepare")
    summary = plan(repo, base, publish_head)
    assert summary["tree_call_count"] > 1
    result = run_request(repo, "emit-handoff", check=False)
    assert result.returncode != 0
    assert "read-through budget" in result.stderr
    assert not (transaction(repo) / "connector" / "handoff.json").exists()
