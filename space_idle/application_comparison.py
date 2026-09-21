from __future__ import annotations

from collections.abc import Iterable, Sequence

from .app_contracts.ui_reports import ComparisonAxisRow, ComparisonValueRow


ComparisonAxisDefinition = tuple[str, str, str, str | None]


def project_comparison_axes(
    axis_definitions: Sequence[ComparisonAxisDefinition],
    candidate_values: Iterable[Sequence[ComparisonValueRow]],
) -> tuple[ComparisonAxisRow, ...]:
    """Project shared comparison axes without attaching ranking semantics.

    Each domain chooses the axes and candidate values it owns.  This helper only
    detects whether the Application-projected values differ, so Presentation can
    highlight meaningful differences without reimplementing domain judgement.
    """

    value_sets = tuple(candidate_values)
    if len(value_sets) < 2:
        return ()
    lookups = tuple(
        {value.axis_key: value for value in values}
        for values in value_sets
    )
    axes: list[ComparisonAxisRow] = []
    for key, label, value_kind, unit in axis_definitions:
        values = tuple(lookup.get(key) for lookup in lookups)
        first = values[0]
        differs = any(not _comparison_value_equal(first, value) for value in values[1:])
        axes.append(
            ComparisonAxisRow(
                key=key,
                label=label,
                value_kind=value_kind,
                unit=unit,
                differs=differs,
            )
        )
    return tuple(axes) if any(axis.differs for axis in axes) else ()


def _comparison_value_equal(
    left: ComparisonValueRow | None,
    right: ComparisonValueRow | None,
) -> bool:
    if left is None or right is None:
        return left is right
    if left.text_value is not None or right.text_value is not None:
        return left.text_value == right.text_value
    if left.number_value is None or right.number_value is None:
        return left.number_value is right.number_value
    return abs(float(left.number_value) - float(right.number_value)) <= 1e-9
