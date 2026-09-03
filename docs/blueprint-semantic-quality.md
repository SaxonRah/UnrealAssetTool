# Blueprint semantic-quality acceptance

Issue #23 is no longer about building the generic Blueprint semantic layer. Coverage is already structurally complete on the accepted GASP gate; the remaining task was to prove that representative derived statements/control are useful and faithful enough for human/AI project understanding.

This acceptance is deliberately split into two axes.

## 1. Machine-checkable integrity

`uatool semantic-quality-case` validates one exact Blueprint against the existing derived streams and reports `structural_quality_ok`.

The machine gate rejects cases with:

- fallback or opaque semantic nodes;
- executable/boundary semantic nodes missing their statement row;
- orphan statement rows;
- control edges whose source/target blocks do not exist;
- a present `blueprint_control_edges.jsonl` stream whose cardinality disagrees with execution-block edges for the Blueprint;
- control-edge endpoint identity that disagrees with the authoritative execution-block edge, including source/target block, node, and exec-pin identity;
- function calls with no exact function/symbol identity;
- writes with no exact symbol/target identity;
- dependency-bearing statements whose dependencies cannot be rendered back into readable expressions.

Branch/switch condition text is displayed separately for semantic review. It is not currently a hard structural defect because uncommon historical control shapes may remain exact in endpoint/pin provenance without a compact rendered condition.

### Control-flow schema 2

Real Enhanced Input review exposed an important fidelity defect in control-flow schema 1: the authoritative execution-block edge preserved `target_node_id` and `target_pin_name`, but the decorated `blueprint_control_edges.jsonl` row discarded them. Distinct authored routes into different exec pins on one target node/block could therefore collapse into the same apparent destination.

Control-flow schema 2 preserves exact target node and target exec-pin identity one-to-one with the authoritative execution-block edge. The quality gate treats endpoint loss as a structural defect, and reports render the target exec pin when present.

This remains derived-only. Existing canonical Blueprint scans can be upgraded with `uatool derive`; no Unreal rescan is required.

## 2. Human/AI semantic coherence

Passing the structural gate does **not** automatically mean a case is semantically accepted.

The report therefore emits bounded high-signal statements and control clauses so a reviewer can check that:

- calls preserve the actual function target and argument/data provenance;
- assignments/struct writes preserve the authored target and value/dependency provenance;
- branch/switch conditions express the actual canonical dependencies;
- execution blocks and outgoing control labels explain authored flow without pretending to execute it;
- event/function boundaries remain recognizable;
- Enhanced Input event outputs remain distinguishable where authored;
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

## Accepted real-corpus cases

The issue #23 completion gate is satisfied by three independently reviewed cases.

### 1. GASP Mover — accepted

Blueprint:

```text
/Game/Blueprints/SandboxCharacter_Mover.SandboxCharacter_Mover
```

Machine result:

```text
structural_quality_ok=True
fallback_nodes=0
opaque_nodes=0
missing_statement_nodes=0
orphan_statement_nodes=0
missing_control_blocks=0
control_cardinality_mismatch=0
missing_call_identity=0
missing_write_identity=0
dependency_render_gaps=0
```

The report preserves meaningful authored behavior including:

- the ordered `ReceiveTick` update chain;
- Mover input collection extraction into authored pre/post-sim state;
- movement-mode switch cases;
- gait/sprint/walk/rotation-mode decision dependencies;
- crouch/twin-stick/teleport branch polarity and value provenance.

### 2. ContentExamples StateTree HUD / UMG — accepted

Blueprint:

```text
/Game/ExampleContent/StateTree/Blueprints/Gameplay/WBP_PlayerHUD_StateTree.WBP_PlayerHUD_StateTree
```

Machine result after control-flow schema 2:

```text
structural_quality_ok=True
control_identity_mismatch=0
```

The semantic view preserves authored UI/state presentation behavior including quest-container visibility toggling, quest-type switching, formatted progress/completion text, interaction text, and skill-name updates. Control edges retain target exec-pin identity where available.

### 3. ContentExamples Enhanced Input — accepted

Blueprint:

```text
/Game/ExampleContent/EnhancedInput/Blueprints/CowInputDemo/BP_EnhancedInput_CowDemo_TriggerStates.BP_EnhancedInput_CowDemo_TriggerStates
```

Machine result after control-flow schema 2:

```text
structural_quality_ok=True
control_identity_mismatch=0
```

The semantic view preserves the authored Enhanced Input event and distinct event outputs:

```text
Started
Ongoing
Triggered
Completed
Canceled
```

It also preserves the charge/reset/material/tick flow and, critically, distinguishes the two authored routes into the same Gate macro node:

```text
Open=false -> Gate.Close
Open=true  -> Gate.Open
```

That distinction was lost in schema 1 and was the architecture-level defect found by the quality review. Schema 2 fixes it without changing canonical scanner data.

## Issue #23 completion

The original completion condition is now met:

1. `SandboxCharacter_Mover` accepted;
2. unrelated UI/UMG + StateTree HUD case accepted;
3. unrelated Enhanced Input case accepted;
4. the only architecture-level semantic defect discovered during review was fixed and revalidated on the real corpus.

Future semantic vocabulary, rendering, and readability improvements are ordinary depth work. They do not require keeping the original generic Blueprint semantic-layer construction issue open.
