"""Private Phase 2 extractor benchmarks, disagreement flags, and scoring."""

from __future__ import annotations

import base64
import html
import json
import platform
import re
import shutil
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from difflib import SequenceMatcher
from importlib import resources
from itertools import combinations
from pathlib import Path
from statistics import mean
from typing import Any

import yaml
from jsonschema import Draft202012Validator

from doc_evidence.config import AppConfig
from doc_evidence.docling_adapter import DoclingExtractor
from doc_evidence.errors import BenchmarkError, DocEvidenceError
from doc_evidence.extraction import (
    ExtractionResult,
    NormalizedPage,
    command_version,
    run_command,
)
from doc_evidence.marker_adapter import MarkerExtractor
from doc_evidence.ocrmypdf_adapter import OcrMyPdfExtractor
from doc_evidence.platform_paths import extended_length_path
from doc_evidence.util import (
    atomic_write_json,
    atomic_write_text,
    compact_timestamp,
    hash_file,
    hash_json,
    isoformat_z,
)

BENCHMARK_SCHEMA_VERSION = 1
_WORD = re.compile(r"[^\W_]+", re.UNICODE)
_NUMBER = re.compile(
    r"(?<!\w)[+-]?(?:"
    r"\d{1,3}(?:[.'’\u202f]\d{3})+(?:,\d+)?|"
    r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|"
    r"\d+(?:[.,]\d+)?"
    r")%?"
)


@dataclass(frozen=True)
class BenchmarkResult:
    run_id: str
    run_dir: Path
    report_path: Path
    review_path: Path
    html_path: Path
    summary: dict[str, Any]


def _load_schema(name: str) -> dict[str, Any]:
    path = resources.files("doc_evidence").joinpath(f"schema_files/{name}")
    return json.loads(path.read_text(encoding="utf-8"))


def _validate(value: object, schema_name: str, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise BenchmarkError(f"{label} root must be a mapping")
    errors = sorted(
        Draft202012Validator(_load_schema(schema_name)).iter_errors(value),
        key=lambda item: list(item.path),
    )
    if errors:
        messages = []
        for error in errors:
            location = ".".join(str(part) for part in error.absolute_path) or "<root>"
            messages.append(f"{location}: {error.message}")
        raise BenchmarkError(f"invalid {label}:\n  - " + "\n  - ".join(messages))
    return value


def load_suite(path: Path) -> tuple[dict[str, Any], str]:
    suite_path = path.expanduser().resolve()
    if not suite_path.is_file():
        raise BenchmarkError(f"benchmark suite does not exist: {suite_path}")
    try:
        raw = yaml.safe_load(suite_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as error:
        raise BenchmarkError(f"cannot read benchmark suite: {error}") from error
    suite = _validate(raw, "benchmark-suite.schema.json", "benchmark suite")
    return suite, hash_json(suite)


def _load_manifest(config: AppConfig) -> dict[str, dict[str, Any]]:
    path = config.store / "manifests" / "latest.jsonl"
    if not path.is_file():
        raise BenchmarkError(
            "no latest inventory manifest; run doc-evidence inventory first"
        )
    records: dict[str, dict[str, Any]] = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            record = json.loads(line)
            records[record["document_id"]] = record
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError) as error:
        raise BenchmarkError(f"cannot read latest manifest: {error}") from error
    return records


def _resolve_source(config: AppConfig, record: dict[str, Any]) -> Path:
    roots = {
        collection.id: extended_length_path(collection.source)
        for collection in config.collections
    }
    for source in record.get("sources", []):
        root = roots.get(source.get("collection_id"))
        if root is None:
            continue
        candidate = root / source["path"]
        if candidate.is_file():
            digest = hash_file(candidate).content_sha256
            if digest == record["content_sha256"]:
                return candidate
    raise BenchmarkError(
        f"no unchanged source path for {record.get('document_id', '<unknown>')}"
    )


def _poppler_result(config: AppConfig, record: dict[str, Any]) -> ExtractionResult:
    raw_artifact = record.get("extraction_artifact_path")
    if not raw_artifact:
        raise BenchmarkError(f"no Poppler artifact for {record['document_id']}")
    run_dir = config.store / raw_artifact
    try:
        run = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
        text = (run_dir / "text.txt").read_text(encoding="utf-8")
        rows = json.loads((run_dir / "pages.json").read_text(encoding="utf-8"))
        pages = tuple(
            NormalizedPage(
                page_number=int(row["page_number"]),
                text=text[int(row["start_offset"]) : int(row["end_offset"])],
                character_count=int(row["character_count"]),
                non_whitespace_character_count=int(
                    row["non_whitespace_character_count"]
                ),
            )
            for row in rows
        )
    except (
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        KeyError,
        TypeError,
        ValueError,
    ) as error:
        raise BenchmarkError(
            f"cannot load Poppler artifact for {record['document_id']}: {error}"
        ) from error
    return ExtractionResult(
        extractor_id="poppler",
        run_id=run["run_id"],
        run_key=run["run_key"],
        artifact_path=raw_artifact,
        status=run["status"],
        pages=pages,
        warnings=tuple(run.get("warnings", [])),
        cache_hit=True,
        runtime_seconds=0.0,
        descriptor=run.get("descriptor", {}),
        raw_artifacts=run.get("raw_outputs", {}),
    )


def _normalize(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _tokens(value: str) -> set[str]:
    return {
        token.casefold()
        for token in _WORD.findall(unicodedata.normalize("NFKC", value))
    }


def _number_tokens(value: str) -> set[str]:
    tokens = set()
    for match in _NUMBER.finditer(unicodedata.normalize("NFKC", value)):
        token = re.sub(r"[\u202f'’]", "", match.group(0)).rstrip("%")
        if "," in token and "." in token:
            if token.rfind(".") > token.rfind(","):
                token = token.replace(",", "")
            else:
                token = token.replace(".", "").replace(",", ".")
        elif "," in token:
            tail = token.rsplit(",", 1)[1]
            token = token.replace(",", "" if len(tail) == 3 else ".")
        tokens.add(token)
    return tokens


def _jaccard(left: set[str], right: set[str]) -> float:
    union = left | right
    return 1.0 if not union else len(left & right) / len(union)


def _page(result: ExtractionResult, page_number: int) -> NormalizedPage | None:
    return next(
        (page for page in result.pages if page.page_number == page_number), None
    )


def _comparison(
    left: ExtractionResult,
    right: ExtractionResult,
    page_number: int,
) -> dict[str, Any]:
    left_page = _page(left, page_number)
    right_page = _page(right, page_number)
    left_text = left_page.text if left_page else ""
    right_text = right_page.text if right_page else ""
    left_normal = _normalize(left_text)
    right_normal = _normalize(right_text)
    left_numbers = _number_tokens(left_text)
    right_numbers = _number_tokens(right_text)
    flags = []
    if left_page is None or right_page is None:
        flags.append({"severity": "high", "kind": "missing_page"})
    elif bool(left_normal) != bool(right_normal):
        flags.append({"severity": "high", "kind": "empty_text_disagreement"})
    if left_numbers != right_numbers:
        flags.append(
            {
                "severity": "high",
                "kind": "numeric_token_disagreement",
                "only_left": sorted(left_numbers - right_numbers)[:50],
                "only_right": sorted(right_numbers - left_numbers)[:50],
            }
        )
    character_similarity = SequenceMatcher(None, left_normal, right_normal).ratio()
    if left_normal and right_normal and character_similarity < 0.75:
        flags.append({"severity": "medium", "kind": "low_character_similarity"})
    return {
        "page": page_number,
        "left": left.extractor_id,
        "right": right.extractor_id,
        "character_similarity": round(character_similarity, 6),
        "token_jaccard": round(_jaccard(_tokens(left_text), _tokens(right_text)), 6),
        "numeric_token_jaccard": round(_jaccard(left_numbers, right_numbers), 6),
        "length_ratio": round(
            min(len(left_text), len(right_text)) / max(len(left_text), len(right_text)),
            6,
        )
        if left_text or right_text
        else 1.0,
        "flags": flags,
    }


def _evaluate_assertion(
    assertion: dict[str, Any], result: ExtractionResult
) -> dict[str, Any]:
    page_number = assertion.get("page")
    if assertion["kind"] == "page_count":
        actual: Any = result.page_count
        passed = actual == int(assertion["value"])
    else:
        page = _page(result, int(page_number)) if page_number else None
        text = page.text if page else ""
        expected = str(assertion["value"])
        if assertion["kind"] == "contains_text":
            passed = _normalize(expected) in _normalize(text)
            actual = passed
        elif assertion["kind"] == "regex":
            passed = re.search(expected, text, re.MULTILINE) is not None
            actual = passed
        elif assertion["kind"] == "numeric_token":
            expected_numbers = _number_tokens(expected)
            actual_numbers = _number_tokens(text)
            passed = bool(expected_numbers) and expected_numbers <= actual_numbers
            actual = sorted(actual_numbers)
        else:
            passed = False
            actual = None
    return {
        "assertion_id": assertion["id"],
        "kind": assertion["kind"],
        "page": page_number,
        "expected": assertion["value"],
        "actual": actual,
        "manually_verified": assertion["manually_verified"],
        "passed": passed,
    }


def _render_page(source: Path, destination: Path, page_number: int) -> str | None:
    executable = shutil.which("pdftoppm")
    if executable is None:
        return "pdftoppm not found"
    destination.parent.mkdir(parents=True, exist_ok=True)
    stem = destination.with_suffix("")
    result = run_command(
        [
            executable,
            "-f",
            str(page_number),
            "-l",
            str(page_number),
            "-singlefile",
            "-r",
            "144",
            "-png",
            str(source),
            str(stem),
        ],
        180,
    )
    if result.returncode != 0 or not destination.is_file():
        return result.stderr or f"pdftoppm exited with status {result.returncode}"
    return None


def _extractors(ids: list[str], languages: tuple[str, ...]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for identifier in ids:
        if identifier == "ocrmypdf-tesseract":
            result[identifier] = OcrMyPdfExtractor(languages)
        elif identifier == "docling-standard":
            result[identifier] = DoclingExtractor()
        elif identifier == "marker-fast":
            result[identifier] = MarkerExtractor()
        elif identifier != "poppler":
            raise BenchmarkError(f"unsupported extractor: {identifier}")
    return result


def _review_template(suite_id: str, run_id: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "suite_id": suite_id,
        "benchmark_run_id": run_id,
        "reviewer": "",
        "created_at": None,
        "ratings": [],
    }


def _embedded_render_sources(
    report: dict[str, Any], run_dir: Path
) -> dict[str, str | None]:
    """Return data URIs for review renders without trusting report paths."""
    root = run_dir.resolve()
    sources: dict[str, str | None] = {}
    for document in report["documents"]:
        for page in document["pages"]:
            render = page["render"]
            candidate = (root / render).resolve()
            try:
                candidate.relative_to(root)
            except ValueError as error:
                raise BenchmarkError(
                    f"review render escapes benchmark run directory: {render}"
                ) from error
            if not candidate.is_file():
                sources[render] = None
                continue
            encoded = base64.b64encode(candidate.read_bytes()).decode("ascii")
            sources[render] = f"data:image/png;base64,{encoded}"
    return sources


def _review_html(
    report: dict[str, Any], template: dict[str, Any], run_dir: Path
) -> str:
    payload = json.dumps(
        {
            "report": report,
            "template": template,
            "render_sources": _embedded_render_sources(report, run_dir),
        },
        ensure_ascii=False,
    ).replace("</", "<\\/")
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Extractor calibration — {html.escape(report["suite_id"])}</title>
<style>
:root {{ color-scheme: light dark; font: 15px system-ui,sans-serif; }} body {{ margin: 0 auto; max-width: 1600px; padding: 24px; }}
.case {{ border-top: 3px solid #777; margin-top: 36px; padding-top: 16px; }} .grid {{ display:grid; grid-template-columns:minmax(360px,1fr) 2fr; gap:16px; align-items:start; }}
img {{ width:100%; height:auto; border:1px solid #888; background:white; }} .render-error {{ border:1px solid #b33; padding:16px; color:#b33; }} .outputs {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(300px,1fr)); gap:12px; }}
.engine {{ border:1px solid #888; border-radius:8px; padding:12px; min-width:0; }} pre {{ white-space:pre-wrap; overflow-wrap:anywhere; max-height:520px; overflow:auto; background:#8882; padding:10px; }}
.ratings label {{ display:block; margin:7px 0; }} select,textarea,input {{ font:inherit; }} textarea {{ width:100%; min-height:54px; }} .flags {{ color:#b33; }} .toolbar {{ position:sticky; top:0; background:Canvas; padding:10px 0; z-index:2; }}
</style></head><body><div class="toolbar"><strong>Human calibration</strong> — 0 unusable, 4 exact/useful. Agreement is not truth.
 Reviewer <input id="reviewer"> <button id="export">Export review JSON</button> <span id="saved"></span></div><main id="app"></main>
<script>const DATA={payload}; const KEY='doc-evidence-review:'+DATA.report.benchmark_run_id; let review=JSON.parse(localStorage.getItem(KEY)||JSON.stringify(DATA.template));
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c]));
const get=(d,p,e)=>{{let r=review.ratings.find(x=>x.document_id===d&&x.page===p&&x.extractor_id===e);if(!r){{r={{document_id:d,document_class:'',page:p,extractor_id:e,reviewed:false,text_accuracy:null,numeric_fidelity:null,reading_order:null,table_structure:null,contains_invented_values:false,notes:''}};review.ratings.push(r)}}return r}};
const save=()=>{{review.reviewer=document.querySelector('#reviewer').value;review.created_at=new Date().toISOString();localStorage.setItem(KEY,JSON.stringify(review));document.querySelector('#saved').textContent='saved locally '+new Date().toLocaleTimeString()}};
document.querySelector('#reviewer').value=review.reviewer||''; let out='';
for(const d of DATA.report.documents) for(const p of d.pages){{const src=DATA.render_sources[p.render];const visual=src?`<img src="${{src}}" alt="Rendered source page ${{p.page}}">`:`<div class="render-error">Page render unavailable: ${{esc(p.render_error||p.render)}}</div>`;out+=`<section class="case"><h2>${{esc(d.path_hint||d.document_id)}} — page ${{p.page}} <small>${{esc(d.document_class)}}</small></h2><div class="grid">${{visual}}<div class="outputs">`;for(const e of p.outputs){{const r=get(d.document_id,p.page,e.extractor_id);r.document_class=d.document_class;const opts=(v,n)=>`<label>${{n}} <select data-k="${{v}}"><option value="">— not rated —</option><option value="0">0 unusable</option><option value="1">1 poor</option><option value="2">2 mixed</option><option value="3">3 good</option><option value="4">4 exact</option></select></label>`;out+=`<article class="engine" data-d="${{d.document_id}}" data-p="${{p.page}}" data-e="${{e.extractor_id}}"><h3>${{esc(e.extractor_id)}} — ${{esc(e.status)}}</h3><div class="flags">${{esc(e.flags.join(', '))}}</div><pre>${{esc(e.text)}}</pre><div class="ratings"><label><input type="checkbox" data-k="reviewed"> Review complete</label>${{opts('text_accuracy','Text accuracy')}}${{opts('numeric_fidelity','Numeric fidelity')}}${{opts('reading_order','Reading order')}}${{opts('table_structure','Table structure (leave blank if not applicable)')}}<label><input type="checkbox" data-k="contains_invented_values"> Invented/unsupported value</label><textarea data-k="notes" placeholder="Specific errors or corrections"></textarea></div></article>`}}out+='</div></div></section>'}}document.querySelector('#app').innerHTML=out;
for(const a of document.querySelectorAll('article')){{const r=get(a.dataset.d,+a.dataset.p,a.dataset.e);for(const el of a.querySelectorAll('[data-k]')){{const k=el.dataset.k;if(el.type==='checkbox')el.checked=!!r[k];else el.value=r[k]??'';el.addEventListener('change',()=>{{r[k]=el.type==='checkbox'?el.checked:(el.tagName==='TEXTAREA'?el.value:(el.value===''?null:+el.value));save()}})}}}}document.querySelector('#reviewer').addEventListener('change',save);
document.querySelector('#export').onclick=()=>{{save();const blob=new Blob([JSON.stringify(review,null,2)+'\\n'],{{type:'application/json'}});const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=DATA.report.suite_id+'-'+DATA.report.benchmark_run_id+'-review.json';a.click();URL.revokeObjectURL(a.href)}};</script></body></html>"""


def run_benchmark(config: AppConfig, suite_path: Path) -> BenchmarkResult:
    suite, suite_hash = load_suite(suite_path)
    manifest = _load_manifest(config)
    run_id = f"{compact_timestamp()}-{suite_hash[:12]}"
    run_dir = config.store / "benchmarks" / suite["suite_id"] / "runs" / run_id
    render_dir = run_dir / "renders"
    engine_ids = list(suite["extractors"])
    engines = _extractors(engine_ids, config.languages)
    report_documents = []
    all_flags = 0

    for case in suite["documents"]:
        record = manifest.get(case["document_id"])
        if record is None:
            raise BenchmarkError(
                f"document not in latest manifest: {case['document_id']}"
            )
        if record.get("media_type") != "application/pdf":
            raise BenchmarkError(
                f"benchmark document is not a PDF: {case['document_id']}"
            )
        source = _resolve_source(config, record)
        blob_dir = config.store / record["artifact_path"]
        selected_ids = case.get("extractors", engine_ids)
        results: dict[str, ExtractionResult] = {}
        for identifier in selected_ids:
            try:
                results[identifier] = (
                    _poppler_result(config, record)
                    if identifier == "poppler"
                    else engines[identifier].extract(
                        source, blob_dir, record["content_sha256"], config.store
                    )
                )
            except (
                DocEvidenceError,
                OSError,
                UnicodeError,
                json.JSONDecodeError,
                KeyError,
                TypeError,
                ValueError,
            ) as error:
                results[identifier] = ExtractionResult(
                    extractor_id=identifier,
                    run_id=f"{identifier}:failed",
                    run_key="failed",
                    artifact_path="",
                    status="error",
                    pages=(),
                    warnings=(f"{type(error).__name__}: {error}",),
                    cache_hit=False,
                    runtime_seconds=0.0,
                    descriptor={},
                    raw_artifacts={},
                )
        comparisons = [
            _comparison(results[left], results[right], page_number)
            for page_number in case["pages"]
            for left, right in combinations(selected_ids, 2)
        ]
        all_flags += sum(len(item["flags"]) for item in comparisons)
        assertions = {
            identifier: [
                _evaluate_assertion(assertion, result)
                for assertion in case.get("assertions", [])
            ]
            for identifier, result in results.items()
        }
        page_reports = []
        for page_number in case["pages"]:
            render_name = f"{record['content_sha256'][:16]}-p{page_number:04d}.png"
            render_error = _render_page(source, render_dir / render_name, page_number)
            outputs = []
            for identifier in selected_ids:
                result = results[identifier]
                page = _page(result, page_number)
                flags = [
                    flag["kind"]
                    for comparison in comparisons
                    if comparison["page"] == page_number
                    and identifier in (comparison["left"], comparison["right"])
                    for flag in comparison["flags"]
                ]
                outputs.append(
                    {
                        "extractor_id": identifier,
                        "status": result.status,
                        "text": page.text if page else "",
                        "flags": sorted(set(flags)),
                    }
                )
            page_reports.append(
                {
                    "page": page_number,
                    "render": f"renders/{render_name}",
                    "render_error": render_error,
                    "outputs": outputs,
                }
            )
        report_documents.append(
            {
                "document_id": case["document_id"],
                "document_class": case["document_class"],
                "path_hint": case.get("path_hint") or record["sources"][0]["path"],
                "source_paths": [
                    source_item["path"] for source_item in record["sources"]
                ],
                "pages": page_reports,
                "comparisons": comparisons,
                "assertions": assertions,
                "extractor_runs": {
                    identifier: {
                        "run_id": result.run_id,
                        "artifact_path": result.artifact_path,
                        "status": result.status,
                        "cache_hit": result.cache_hit,
                        "runtime_seconds": result.runtime_seconds,
                        "page_count": result.page_count,
                        "table_count": result.table_count,
                        "warnings": list(result.warnings),
                        "descriptor": result.descriptor,
                    }
                    for identifier, result in results.items()
                },
            }
        )

    marker = engines.get("marker-fast")
    stopped_marker_services = marker.stop_services() if marker is not None else []
    extraction_failures = sum(
        run["status"] != "ok"
        for document in report_documents
        for run in document["extractor_runs"].values()
    )
    verified_assertions = [
        item
        for document in report_documents
        for items in document["assertions"].values()
        for item in items
        if item["manually_verified"]
    ]
    summary = {
        "documents": len(report_documents),
        "review_pages": sum(len(document["pages"]) for document in report_documents),
        "extractors": len(engine_ids),
        "disagreement_flags": all_flags,
        "extractor_failures": extraction_failures,
        "marker_services_stopped": len(stopped_marker_services),
        "verified_assertion_results": len(verified_assertions),
        "verified_assertion_passes": sum(
            item["passed"] for item in verified_assertions
        ),
    }
    report = {
        "schema_version": BENCHMARK_SCHEMA_VERSION,
        "suite_id": suite["suite_id"],
        "suite_hash": suite_hash,
        "benchmark_run_id": run_id,
        "created_at": isoformat_z(),
        "config_hash": config.config_hash,
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "pdftoppm_version": command_version(["pdftoppm", "-v"]),
        },
        "methodology": {
            "agreement_is_ground_truth": False,
            "human_scale": "0 unusable, 1 poor, 2 mixed, 3 good, 4 exact/useful",
            "retirement_is_automatic": False,
            "minimum_recommended_reviews_per_class": 5,
        },
        "summary": summary,
        "documents": report_documents,
    }
    template = _review_template(suite["suite_id"], run_id)
    atomic_write_json(run_dir / "report.json", report)
    atomic_write_json(run_dir / "review-template.json", template)
    atomic_write_text(run_dir / "review.html", _review_html(report, template, run_dir))
    pointer_dir = config.store / "benchmarks" / suite["suite_id"]
    atomic_write_json(
        pointer_dir / "latest-run.json",
        {
            "benchmark_run_id": run_id,
            "run_dir": run_dir.relative_to(config.store).as_posix(),
            "report": (run_dir / "report.json").relative_to(config.store).as_posix(),
            "review": (run_dir / "review.html").relative_to(config.store).as_posix(),
        },
    )
    return BenchmarkResult(
        run_id=run_id,
        run_dir=run_dir,
        report_path=run_dir / "report.json",
        review_path=run_dir / "review-template.json",
        html_path=run_dir / "review.html",
        summary=summary,
    )


def score_review(report_path: Path, review_path: Path) -> tuple[Path, dict[str, Any]]:
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
        review = json.loads(review_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise BenchmarkError(f"cannot read report/review: {error}") from error
    review = _validate(review, "review.schema.json", "human review")
    if review["benchmark_run_id"] != report.get("benchmark_run_id"):
        raise BenchmarkError("review belongs to a different benchmark run")
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for rating in review["ratings"]:
        if not rating["reviewed"]:
            continue
        missing_dimensions = [
            dimension
            for dimension in ("text_accuracy", "numeric_fidelity", "reading_order")
            if rating.get(dimension) is None
        ]
        if missing_dimensions:
            raise BenchmarkError(
                "review-complete item is missing rating(s) for "
                + ", ".join(missing_dimensions)
                + f": {rating['document_id']} page {rating['page']} / "
                + rating["extractor_id"]
            )
        groups[(rating["document_class"], rating["extractor_id"])].append(rating)
    scorecards = []
    for (document_class, extractor_id), ratings in sorted(groups.items()):
        dimension_values: dict[str, list[int]] = defaultdict(list)
        for rating in ratings:
            for dimension in (
                "text_accuracy",
                "numeric_fidelity",
                "reading_order",
                "table_structure",
            ):
                value = rating.get(dimension)
                if value is not None:
                    dimension_values[dimension].append(value)
        combined = [value for values in dimension_values.values() for value in values]
        invented = sum(bool(rating["contains_invented_values"]) for rating in ratings)
        support = len(ratings)
        average = mean(combined) if combined else 0.0
        if support < 5:
            recommendation = "experimental-insufficient-calibration"
        elif invented / support >= 0.2 or average < 2.0:
            recommendation = "corroborating-only-review-retirement"
        elif average >= 3.5 and invented == 0:
            recommendation = "candidate-default-for-class"
        else:
            recommendation = "fallback-or-second-opinion"
        scorecards.append(
            {
                "document_class": document_class,
                "extractor_id": extractor_id,
                "reviewed_pages": support,
                "dimension_means": {
                    key: round(mean(values), 3)
                    for key, values in sorted(dimension_values.items())
                },
                "combined_mean": round(average, 3),
                "invented_value_reviews": invented,
                "recommendation": recommendation,
                "automatic_policy_change": False,
            }
        )
    scorecard = {
        "schema_version": 1,
        "suite_id": report["suite_id"],
        "benchmark_run_id": report["benchmark_run_id"],
        "reviewer": review["reviewer"],
        "scored_at": isoformat_z(),
        "scorecards": scorecards,
        "policy_note": "Recommendations require explicit approval; agreement is not ground truth.",
    }
    output = (
        report_path.parent
        / f"scorecard-{re.sub(r'[^A-Za-z0-9_-]+', '-', review['reviewer'] or 'anonymous')}.json"
    )
    atomic_write_json(output, scorecard)
    return output, scorecard
