from app.modules.document_analysis.schemas import Report, RunView


def markdown_report(run: RunView) -> str:
    if run.report is None:
        return ""
    report: Report = run.report
    lines = [
        "# 法律文书分析报告",
        "",
        f"分析要求：{run.instruction}",
        "",
        f"任务编号：{run.id}",
        "",
        f"生成状态：{run.status}",
        "",
        "## 分析概览",
        "",
        report.summary,
    ]
    levels = {"high": "高", "medium": "中", "low": "低", "info": "提示"}
    for index, finding in enumerate(report.findings, 1):
        lines.extend(
            [
                "",
                f"## {index}. {finding.title}",
                "",
                f"风险程度：{levels[finding.severity]}；依据状态：{finding.evidence_status}",
                "",
                finding.analysis,
            ]
        )
        if finding.suggestion:
            lines.extend(["", "建议：" + finding.suggestion])
        for citation in finding.document_citations:
            lines.extend(
                [
                    "",
                    f"原文 [{citation.document_id} / 版本 {citation.revision} / "
                    f"{citation.span_id}]：",
                    "",
                    *["> " + line for line in citation.quote.splitlines()],
                ]
            )
        for citation in finding.law_citations:
            source = next(
                (source for source in report.sources if source.id == citation.source_id), None
            )
            lines.extend(
                [
                    "",
                    f"依据 [{citation.source_id}] {source.title if source else ''}：",
                    "",
                    *["> " + line for line in citation.quote.splitlines()],
                ]
            )
        if finding.uncertainty:
            lines.extend(["", "待核实：" + finding.uncertainty])
    for title, items in (
        ("事实与时间线", report.timeline),
        ("待补充材料", report.missing_materials),
        ("分析范围与限制", report.limitations),
    ):
        if items:
            lines.extend(["", "## " + title, "", *["- " + item for item in items]])
    if report.review_summary:
        lines.extend(["", "## 复核意见", "", report.review_summary])
    if report.sources:
        lines.extend(["", "## 来源"])
        for source in report.sources:
            lines.extend(
                [
                    "",
                    f"### {source.title}",
                    "",
                    f"编号：{source.id}",
                    "",
                    f"来源：{source.source}",
                    "",
                    source.content,
                ]
            )
    return "\n".join(lines) + "\n"
