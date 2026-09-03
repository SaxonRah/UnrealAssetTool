# Blueprint semantic-quality acceptance

Issue #23 is no longer about building the generic Blueprint semantic layer. Coverage is already structurally complete on the accepted GASP gate; the remaining task is to prove that representative derived statements/control are useful and faithful enough for human/AI project understanding.

This acceptance is deliberately split into two axes.

## 1. Machine-checkable integrity

`uatool semantic-quality-case` validates one exact Blueprint against the existing derived streams and reports `structural_quality_ok`.

The machine gate rejects cases with:

- fallback or opaque semantic nodes;
- executable/boundary semantic nodes missing their statement row;
- orphan statement rows;
- control edges whose source/target blocks do not exist;
- a present `blueprint_control_edges.jsonl` stream whose cardinality disagrees with execution-block edges for the Blueprint;
- function calls with no exact function/symbol identity;
- writes with no exact symbol/target identity;
- dependency-bearing statements whose dependencies cannot be rendered back into readable expressions.

Branch/switch condition text is displayed separately for semantic review. It is not currently a hard structural defect because uncommon historical control shapes may remain exact in endpoint/pin provenance without a compact rendered condition.

## 2. Human/AI semantic coherence

Passing the structural gate does **not** automatically mean a case is semantically accepted.

The report therefore emits bounded high-signal statements and control clauses so a reviewer can check that:

- calls preserve the actual function target and argument/data provenance;
- assignments/struct writes preserve the authored target and value/dependency provenance;
- branch/switch conditions express the actual canonical dependencies;
- execution blocks and outgoing control labels explain authored flow without pretending to execute it;
- event/function boundaries remain recognizable;
- no domain-specific runtime behavior is invented from asset names.

Every report states:

```text
diagnostic_only=True
schema_promotion=False
runtime_state_captured=False
human_semantic_review_required=True
```

## Candidate discovery

`semantic-quality-candidates` ranks exact Blueprint paths using only authored semantic complexity:

- statement count;
- dependency-bearing statements;
- calls/writes;
- branch/switch/sequence control;
- control edges;
- events/functions;
- delegate semantic relations.

The score is discovery-only. It does not infer gameplay domain from asset names.

Example:

```powershell
python scripts\uatool.py semantic-quality-candidates `
    "E:\TheDigitalGame\ue\ContentExamples\.uatool" `
    --limit 30 `
    --report "E:\TheDigitalGame\ue\ContentExamples\.uatool\semantic-quality-candidates.txt"
```

A path substring can be used only as a user-directed navigation filter:

```powershell
python scripts\uatool.py semantic-quality-candidates `
    "E:\TheDigitalGame\ue\GameAnimationSample\.uatool" `
    --contains "SandboxCharacter_Mover"
```

## One exact quality case

```powershell
python scripts\uatool.py semantic-quality-case `
    "E:\TheDigitalGame\ue\GameAnimationSample\.uatool" `
    "/Game/Blueprints/SandboxCharacter_Mover.SandboxCharacter_Mover" `
    --example-limit 50 `
    --report "E:\TheDigitalGame\ue\GameAnimationSample\.uatool\SandboxCharacter_Mover.semantic-quality.txt"
```

The command returns success only when the machine-checkable structural quality gate passes. Semantic coherence is still reviewed from the emitted statements/control.

## Issue #23 completion rule

Close #23 when real reports document accepted semantic quality for:

1. `SandboxCharacter_Mover`; and
2. at least two unrelated Blueprint-heavy categories.

Preferred unrelated categories remain:

- animation/gameplay integration;
- Enhanced Input flow;
- UI/UMG behavior;
- Smart Object interaction;
- ordinary gameplay state/branching/delegate patterns.

The category choice must be established by exact class/component/event/reference evidence or by the reviewer explicitly selecting the authored Blueprint. It must not be inferred merely from an asset name.

Once those cases are accepted and no architecture-level defect remains, future semantic vocabulary improvements become ordinary depth work rather than keeping the original semantic-layer issue open.
