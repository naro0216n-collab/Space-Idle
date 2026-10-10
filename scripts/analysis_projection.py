"""Read-only experiment JSON consumers: tabular projections and scoped diagrams.

This module never reads or modifies gameplay State.  It does not attribute
anonymous Inventory admissions to an invented production/transport source.
"""
from __future__ import annotations

import argparse
import csv
from html import escape
import json
from pathlib import Path
import sys


def csv_rows(payload: dict, table: str):
    if table not in {"inventory_movements", "custody_transfers", "allocations", "state_metrics", "cargo_positions", "reconciliation"}:
        raise ValueError(f"unknown typed projection: {table}")
    for run in payload["runs"]:
        if table in {"inventory_movements", "custody_transfers", "allocations"}:
            for trace in run["canonical_traces"]:
                for item in trace[table]:
                    yield {"case": run["name"], "day": trace["day"], **item}
        elif table == "reconciliation":
            for item in run["flow_reconciliation"]:
                yield {"case": run["name"], **item}
        else:
            key = "metrics" if table == "state_metrics" else table
            for observation in run["observations"]:
                for item in observation[key]:
                    yield {"case": run["name"], "day": observation["day"], **item}


def to_csv(payload: dict, table: str) -> str:
    import io
    rows = list(csv_rows(payload, table))
    out = io.StringIO()
    fields = sorted({key for row in rows for key in row})
    if not fields:
        return ""
    writer = csv.DictWriter(out, fields, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({key: json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else value
                         for key, value in row.items()})
    return out.getvalue()


def _bars(labels: list[str], values: list[float], *, width=870) -> str:
    """Diagram lengths have physical scale, not an inferred shared currency."""
    max_value = max(values, default=0) or 1
    rows = []
    for index, (label, value) in enumerate(zip(labels, values)):
        y = 28 + index * 35
        span = value / max_value * (width - 390)
        rows.append(f'<text x="12" y="{y+12}" font-size="12">{escape(label)}</text>'
                    f'<rect x="340" y="{y}" width="{span:.2f}" height="17" fill="#648ab4" />'
                    f'<text x="{350+span:.2f}" y="{y+13}" font-size="12">{value:.5g}</text>')
    return (f'<svg width="{width}" height="{max(50, 34+len(rows)*35)}" viewBox="0 0 {width} '
            f'{max(50,34+len(rows)*35)}" xmlns="http://www.w3.org/2000/svg">'
            + ''.join(rows) + '</svg>')



def _sankey(flows: dict[tuple[str, str, str], float]) -> str:
    """Signed, owner-local Inventory edges; remote transfer is NOT inferred.

    Each observed inflow is an independent edge from an unknown source, and
    each observed outflow is to an unknown use.  Unknowns are not falsely
    matched to claim cargo delivery or a source activity.
    """
    lanes = sorted({(node, resource) for node, resource, _direction in flows})
    scale = 14 / max(flows.values(), default=1)
    rows = [
        '<text x="2" y="15" font-size="12">供給元未確定</text>',
        '<text x="338" y="15" font-size="12">拠点 / Resource</text>',
        '<text x="740" y="15" font-size="12">用途未確定</text>',
    ]
    for index, (node, resource) in enumerate(lanes):
        y = 40 + 45 * index
        in_amount = flows.get((node, resource, 'inventory_in'), 0)
        out_amount = flows.get((node, resource, 'inventory_out'), 0)
        rows.append(f'<text x="335" y="{y+6}" font-size="12">{escape(node)} / {escape(resource)}</text>')
        for amount, direction, path, color in (
            (in_amount, 'in', f'M 140 {y+14} C 230 {y+14}, 265 {y+14}, 330 {y+14}', '#4b8e9c'),
            (out_amount, 'out', f'M 715 {y+14} C 680 {y+14}, 680 {y+14}, 680 {y+14}', '#ac8a51'),
        ):
            if amount > 0:
                if direction == 'out':
                    path = f'M 620 {y+14} C 670 {y+14}, 680 {y+14}, 715 {y+14}'
                rows.append(f'<path d="{path}" fill="none" stroke="{color}" '
                            f'stroke-width="{max(1,min(18,amount*scale)):.2f}">'
                            f'<title>{direction} {amount:.8g} t / {escape(node)} / {escape(resource)}</title></path>')
                x = 143 if direction == 'in' else 720
                rows.append(f'<text x="{x}" y="{y+33}" font-size="11">{amount:.5g} t</text>')
    height = max(65, 45*len(lanes)+40)
    return (f'<svg width="915" height="{height}" viewBox="0 0 915 {height}" '
            'xmlns="http://www.w3.org/2000/svg">' + ''.join(rows) + '</svg>')


def _fulfillment_heatmap(traces: list[dict]) -> str:
    """Day-indexed actual fulfillment; no zero inserted for absent requests."""
    days = sorted({trace['day'] for trace in traces})
    by_key: dict[tuple, dict[int, tuple[float, float]]] = {}
    for trace in traces:
        for row in trace['allocations']:
            if row['kind'] not in {'activity_execution', 'resource_request', 'service_request'}:
                continue
            key = (row['kind'], row['context_id'], row['subject_id'], row['unit'])
            amounts = by_key.setdefault(key, {})
            requested, allocated = amounts.get(trace['day'], (0.0, 0.0))
            amounts[trace['day']] = requested+row['requested'], allocated+row['allocated']
    parts = ['<table style="border-collapse:collapse;font-size:12px">',
             '<thead><tr><th style="text-align:left">Constraint / Location / Unit</th>']
    parts.extend(f'<th>{day}日</th>' for day in days)
    parts.append('</tr></thead><tbody>')
    for key, measurements in sorted(by_key.items()):
        parts.append(f'<tr><th style="text-align:left;padding:3px">{escape(" / ".join(key))}</th>')
        for day in days:
            value = measurements.get(day)
            if value is None or value[0] <= 0:
                parts.append('<td style="background:#e5e7eb;text-align:center;padding:4px" title="欠測または需要0">—</td>')
            else:
                requested, allocated = value
                ratio = max(0.0, min(1.0, allocated / requested))
                # Saturation is a legibility cue, not a separate eligibility judgment.
                tone = round(92 + 130*ratio)
                parts.append(f'<td style="background:rgb({230-tone//4},{tone},{245-tone//4});'
                             f'text-align:center;padding:4px" '
                             f'title="要求 {requested:.6g} / 割当 {allocated:.6g} {escape(key[3])}">'
                             f'{100*ratio:.0f}%</td>')
        parts.append('</tr>')
    return ''.join(parts) + '</tbody></table>'

def _custody_table(traces: list[dict]) -> str:
    """Only physically paired staging movements get explicit end points."""
    rows = [row for trace in traces for row in trace.get('custody_transfers', ())]
    if not rows:
        return '<p>この期間に確定したOwner間のStaging移管はありません。</p>'
    contents = ['<table><thead><tr><th>日</th><th>Resource</th><th>出所</th>'
                '<th>移管先</th><th>量 [t]</th></tr></thead><tbody>']
    for row in rows:
        contents.append('<tr>' + ''.join(f'<td>{escape(str(value))}</td>' for value in (
            row['day'], row['resource_id'], row['source_owner'], row['destination_owner'],
            f"{row['quantity_t']:.6g}",
        )) + '</tr>')
    return ''.join(contents) + '</tbody></table>'


def project_html(payload: dict) -> str:
    """Static resource-gross-flow and demand-fulfillment charts.

    Unknown source/sink stays unknown, so no misleading node-to-node transfer
    is created from the Inventory ledger alone.
    """
    parts = ['<!doctype html><html lang="ja"><meta charset="utf-8"><title>Space Idle 分析</title>',
             '<style>body{font:14px system-ui;margin:2em;max-width:1050px}section{padding:1em 0;border-bottom:1px solid #bbb}'
             'svg{max-width:100%;height:auto}h2{margin:0 0 1em}small{color:#555}</style>',
             '<h1>Space Idle Canonical Experiment</h1>',
             '<p>確定入出庫と要求・割当を区別。発生源が未確認の入庫と出庫には転送の因果関係を付与しない。</p>']
    for run in payload["runs"]:
        movements = [r for day in run["canonical_traces"] for r in day["inventory_movements"]]
        flows: dict[tuple, float] = {}
        for move in movements:
            if move["direction"] not in {"inventory_in", "inventory_out"}:
                continue
            key = (move["node_id"], move["resource_id"], move["direction"])
            flows[key] = flows.get(key, 0) + move["quantity_t"]
        parts.extend([f'<section><h2>{escape(run["name"])}</h2>',
            f'<small>期間 {run["observations"][0]["day"]}–{run["observations"][-1]["day"]}日、定義hash {escape(run["content_definitions_sha256"][:14])}</small>',
            '<h3>拠点・Resource別の確定Stock入出庫 Sankey [t]</h3>',
            _sankey(flows),
            '<h3>確定した拠点Inventory・所有者Staging間の移管</h3>',
            _custody_table(run['canonical_traces']),
            '<h3>日別需要充足ヒートマップ（実Allocation / 要求）</h3>',
            _fulfillment_heatmap(run['canonical_traces']),
        ])
        unreconciled = [row for row in run['flow_reconciliation'] if abs(row['unattributed_delta_t']) > 1e-7]
        if unreconciled:
            parts.append(f'<p>残差未説明: {len(unreconciled)}件（データを偽装せずJSON参照）</p>')
        parts.append('</section>')
    return ''.join(parts) + '</html>'


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("result", type=Path, help="compare_experiments.py のJSON結果")
    parser.add_argument("--format", choices=("html", "csv"), default="html")
    parser.add_argument("--table", default="inventory_movements",
                        choices=("inventory_movements", "custody_transfers", "allocations", "state_metrics", "cargo_positions", "reconciliation"))
    args = parser.parse_args()
    payload = json.loads(args.result.read_text(encoding="utf-8"))
    sys.stdout.write(to_csv(payload, args.table) if args.format == "csv" else project_html(payload))


if __name__ == "__main__":
    main()
