from app.modules.knowledge.schemas import (
    LegalCategory,
    LegalMetadata,
    ParseIssue,
    ParseResult,
    SourceMetadata,
)

CATEGORY_VALUES: dict[str, LegalCategory] = {
    "宪法": "CONSTITUTION",
    "法律": "LAW",
    "行政法规": "ADMINISTRATIVE_REGULATION",
    "监察法规": "SUPERVISION_REGULATION",
    "地方性法规": "LOCAL_REGULATION",
    "地方法规": "LOCAL_REGULATION",
    "部门规章": "DEPARTMENT_RULE",
    "地方政府规章": "LOCAL_GOVERNMENT_RULE",
    "司法解释": "JUDICIAL_INTERPRETATION",
}


def has_metadata_value(field: str, value: object) -> bool:
    return (
        value is not None and value != "" and not (field == "category" and value == "UNCLASSIFIED")
    )


def merge_source_metadata(
    result: ParseResult, source: SourceMetadata | None, previous: ParseResult | None = None
) -> None:
    original = result.metadata.model_dump()
    human_fields: set[str] = set()
    if previous:
        human_fields = {
            field for field, origin in previous.metadata_sources.items() if origin == "HUMAN"
        }
        # 旧版人工修订没有字段来源记录，只补空缺，避免覆盖已填写的内容。
        if previous.method == "HUMAN" and not previous.metadata_sources:
            human_fields.update(
                field
                for field, value in previous.metadata.model_dump().items()
                if has_metadata_value(field, value)
            )
            human_fields.add("legal_status")
        for field in human_fields.intersection(LegalMetadata.model_fields):
            setattr(result.metadata, field, getattr(previous.metadata, field))
            result.metadata_sources[field] = "HUMAN"
        if "legal_status" in human_fields:
            result.metadata_sources["legal_status"] = "HUMAN"
    if source:
        for field, value in source.metadata.model_dump().items():
            if field in human_fields or not has_metadata_value(field, value):
                continue
            # 只把有真实正文锚点的矛盾列为核对项，不将正文缺失视为矛盾。
            if original[field] != value and any(anchor.field == field for anchor in result.anchors):
                issue_id = f"official_metadata_conflict:{field}"
                if not any(issue.id == issue_id for issue in result.extraction_issues):
                    result.extraction_issues.append(
                        ParseIssue(
                            id=issue_id,
                            code="official_metadata_conflict",
                            severity="WARNING",
                            message=f"官网信息与原文提取的{field_label(field)}不一致，请对照原件核对",
                        )
                    )
            setattr(result.metadata, field, value)
            result.metadata_sources[field] = "OFFICIAL"
        if "legal_status" not in human_fields and source.legal_status != "UNKNOWN":
            result.metadata_sources["legal_status"] = "OFFICIAL"
    changed = {field for field in original if original[field] != getattr(result.metadata, field)}
    result.anchors = [anchor for anchor in result.anchors if anchor.field not in changed]


def field_label(field: str) -> str:
    return {
        "title": "名称",
        "authority": "机关",
        "document_number": "文号",
        "promulgated_on": "公布日期",
        "effective_on": "施行日期",
        "version_label": "版本说明",
        "category": "法规类别",
        "region": "适用地区",
    }.get(field, "元数据")
