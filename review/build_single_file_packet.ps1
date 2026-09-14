param(
    [string]$OutputPath = "outputs/autocontract-ai-review-packet-p5n.md",
    [switch]$Compact
)

$ErrorActionPreference = "Stop"
$workspace = Split-Path -Parent $PSScriptRoot
$destination = Join-Path $workspace $OutputPath

$sources = @(
    "review/AI_REVIEW_PROMPT_P5N.zh-CN.md",
    "docs/history/README_before_organization_2026-09-09.md",
    ".research/semantics_safe_reconfiguration/research_readiness_audit_2026-07-30.zh-CN.md",
    ".research/semantics_safe_reconfiguration/p4_literature_and_github_pressure_test_2026-07-30.zh-CN.md",
    ".research/semantics_safe_reconfiguration/p4a_adapter_burden_postmortem.zh-CN.md",
    ".research/semantics_safe_reconfiguration/p5c_p5g_cedar_integration_and_reorder_postmortem.zh-CN.md",
    ".research/semantics_safe_reconfiguration/p5i_p5j_reorder_capability_v1_postmortem.zh-CN.md",
    ".research/semantics_safe_reconfiguration/p5k_torchvision_real_pair_coverage_postmortem.zh-CN.md",
    ".research/semantics_safe_reconfiguration/p5l_torchvision_relation_algebra_postmortem.zh-CN.md",
    ".research/semantics_safe_reconfiguration/p5m_relation_boundary_falsification_postmortem.zh-CN.md",
    ".research/semantics_safe_reconfiguration/p5n_reorder_final_handoff_postmortem.zh-CN.md",
    ".research/semantics_safe_reconfiguration/literature_matrix.md",
    "benchmark/final_v2/reorder_pair_selection_guide.zh-CN.md",
    "benchmark/final_v1/p5l_torchvision_relation_algebra_protocol.json",
    "benchmark/final_v1/p5m_relation_boundary_falsification_protocol.json",
    "benchmark/final_v2/p5n_reorder_final_handoff_protocol.json",
    "benchmark/final_v1/reorder_capability_v2.schema.json",
    "experiments/autocontract_reorder_capability_v2.py",
    "experiments/autocontract_p5f_reorder_unsoundness.py",
    "experiments/autocontract_p5m_relation_boundary_falsification.py",
    "outputs/autocontract_p5f_reorder_unsoundness.json",
    "outputs/autocontract_p5h_reorder_receipt_trust.json",
    "outputs/autocontract_p5k_torchvision_real_pairs.json",
    "outputs/autocontract_p5l_torchvision_relation_algebra.json",
    "outputs/autocontract_p5m_relation_boundary_falsification.json",
    "outputs/autocontract_p5n_reorder_final_handoff_selftest_attempt0_receipt_false_positive.json",
    "outputs/autocontract_p5n_reorder_final_handoff_selftest.json"
)

if ($Compact) {
    $sources = @(
        "review/AI_REVIEW_PROMPT_P5N.zh-CN.md",
        ".research/semantics_safe_reconfiguration/research_readiness_audit_2026-07-30.zh-CN.md",
        ".research/semantics_safe_reconfiguration/p4_literature_and_github_pressure_test_2026-07-30.zh-CN.md",
        ".research/semantics_safe_reconfiguration/p4a_adapter_burden_postmortem.zh-CN.md",
        ".research/semantics_safe_reconfiguration/p5c_p5g_cedar_integration_and_reorder_postmortem.zh-CN.md",
        ".research/semantics_safe_reconfiguration/p5i_p5j_reorder_capability_v1_postmortem.zh-CN.md",
        ".research/semantics_safe_reconfiguration/p5k_torchvision_real_pair_coverage_postmortem.zh-CN.md",
        ".research/semantics_safe_reconfiguration/p5l_torchvision_relation_algebra_postmortem.zh-CN.md",
        ".research/semantics_safe_reconfiguration/p5m_relation_boundary_falsification_postmortem.zh-CN.md",
        ".research/semantics_safe_reconfiguration/p5n_reorder_final_handoff_postmortem.zh-CN.md",
        "benchmark/final_v2/reorder_pair_selection_guide.zh-CN.md"
    )
}

$builder = New-Object System.Text.StringBuilder
[void]$builder.AppendLine("# AutoContract single-file AI review packet")
[void]$builder.AppendLine("")
[void]$builder.AppendLine("> Snapshot date: 2026-07-31. This is an internal research package, not a finished paper. P5K-P5M are known-corpus calibration; P5N is synthetic administrative readiness; the independent reorder-final benchmark has not been run.")
[void]$builder.AppendLine("> Packet mode: $(if ($Compact) { 'compact narrative; raw JSON and source code are named but not embedded' } else { 'full review artifact with selected source code and raw outputs' }).")
[void]$builder.AppendLine("")
[void]$builder.AppendLine("Repository reference: https://github.com/Ryan041120/autocontract-ml-input-pipelines . The embedded snapshot may be newer than the public remote; embedded hashes define this review artifact. Upload this Markdown file to a fresh AI conversation and ask the reviewer to follow the first embedded prompt.")
[void]$builder.AppendLine("")
[void]$builder.AppendLine("## Embedded source index")
[void]$builder.AppendLine("")

foreach ($relative in $sources) {
    $source = Join-Path $workspace $relative
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
        throw "Missing packet source: $relative"
    }
    $hash = (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash.ToLowerInvariant()
    $length = (Get-Item -LiteralPath $source).Length
    [void]$builder.AppendLine("- ``$relative`` | $length bytes | SHA-256 ``$hash``")
}

foreach ($relative in $sources) {
    $source = Join-Path $workspace $relative
    $content = Get-Content -LiteralPath $source -Raw -Encoding UTF8
    [void]$builder.AppendLine("")
    [void]$builder.AppendLine("---")
    [void]$builder.AppendLine("")
    [void]$builder.AppendLine("# Embedded source: ``$relative``")
    [void]$builder.AppendLine("")
    $extension = [IO.Path]::GetExtension($source)
    if ($extension -in @(".json", ".csv")) {
        $language = if ($extension -eq ".json") { "json" } else { "csv" }
        [void]$builder.AppendLine("``````$language")
        [void]$builder.AppendLine($content.TrimEnd())
        [void]$builder.AppendLine("``````")
    } else {
        [void]$builder.AppendLine($content.TrimEnd())
    }
}

$parent = Split-Path -Parent $destination
New-Item -ItemType Directory -Path $parent -Force | Out-Null
[IO.File]::WriteAllText($destination, $builder.ToString(), (New-Object Text.UTF8Encoding($false)))

$result = Get-Item -LiteralPath $destination
[pscustomobject]@{
    Path = $result.FullName
    Bytes = $result.Length
    SourceFiles = $sources.Count
    SHA256 = (Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash.ToLowerInvariant()
}
