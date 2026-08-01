# Product Landscape and Use Cases

Topic: product-landscape-and-use-cases

**Status:** Initial product and competitive research recorded; intended
operator model accepted; exact identity of the maintainer-recalled Swiss tax
product remains unresolved

**Last researched:** 2026-08-01

## Scope

This topic owns the continuing product-positioning record for Doc Evidence:

- how the project originated and what problem it was built to solve;
- adjacent open-source projects, commercial products, and product categories;
- promising generic and domain-specific use cases;
- the intended division of work between extraction tools, agents, and people;
- the source-to-value-to-form interaction that should guide durable review and
  observation work; and
- claims the product must not make without stronger evidence guarantees.

This is a research and direction record, not authorization for a tactical.
Specific implementation still requires a bounded tactical with its own data,
security, dependency, migration, and validation decisions.

## Origin

Doc Evidence began in commit `4e04f93` as a generic local document-evidence
pipeline, not as a scanner inbox, a generic document-chat application, or a
desktop-shell experiment. Its initial objective was already to:

- inventory heterogeneous collections without modifying their sources;
- identify content independently of its path;
- run and compare multiple extraction engines;
- retain reproducible extraction and page provenance;
- propose structured observations without silently accepting them; and
- supply reviewed source facts to downstream systems.

The first demanding integration was an external private tax workspace. Its
mixed born-digital and scanned documents, multilingual content, forms, tables,
statements, and administrative records made a layered evidence model necessary:

```text
immutable source
  -> extraction representation
  -> candidate observation
  -> reviewed source fact
  -> domain classification and computation
  -> form or report mapping
  -> submission or other downstream output
```

The project must make adjacent layers difficult to confuse. Extracted text is
not a fact. A recognized number is not a tax classification. A reviewed source
amount is not by itself a completed calculation. A populated government form
is not proof that the filing is correct.

The implementation history follows that problem:

1. contracts and safety boundaries;
2. deterministic inventory, hashing, and duplicate detection;
3. reconciliation against the external collection;
4. OCR and layout-parser calibration;
5. an application for inspecting and comparing representations;
6. durable execution, recovery, and desktop-shaped library ownership; and
7. a proposed installed desktop composition.

The UI was initially optional. It became product-defining when extractor
comparison demonstrated that a person needs a good way to inspect source,
output, disagreement, and provenance together.

## Product Thesis

Doc Evidence should become the local evidence workbench between a document
archive and downstream automation.

It answers a different question from a conventional document manager:

> What do these documents support, which machine-derived values remain
> provisional, what has a person actually confirmed, and can every downstream
> value be traced back to the exact source region and processing history?

The strongest concise positioning is **proof before automation**.

The likely durable advantages are:

- immutable sources observed in place rather than an opaque ingest-only copy;
- content, extraction, observation, review, and computation identities that
  remain distinct;
- multiple extractors retained as inspectable representations rather than
  prematurely merged into one answer;
- honest disagreement and uncertainty in the interface;
- local and offline operation for sensitive collections;
- purpose-specific human review that survives re-extraction; and
- versioned domain adapters that can automate work without weakening generic
  provenance.

Doc Evidence should not try to beat a personal document manager at mailroom
automation or an enterprise e-discovery system at legal production. It can
index an existing archive and later exchange data with those systems while
owning the source-to-reviewed-fact boundary.

## Intended Operator Model

The expected user is not a manual transcription operator. The default workflow
should allocate human attention to consequential or uncertain values, while
software performs repetitive collection, extraction, organization, and
provisional assembly.

### Machine and agent responsibilities

An extractor, deterministic rule, model adapter, or agent may:

- inventory and classify documents;
- schedule or select extraction methods;
- preserve and compare raw and normalized representations;
- propose typed values with document, page, and region provenance;
- run arithmetic, format, cross-document, and domain validations;
- identify missing, conflicting, or unusually consequential evidence;
- assemble a provisional source-fact ledger;
- apply a versioned domain pack to provisional computations; and
- map provisional results to named or numbered form fields.

An agent should be able to manage this workflow without pretending that its
own judgment is a human confirmation. It must carry unresolved conflicts and
unreviewed inputs forward visibly or abstain according to policy.

### Human responsibilities

A person may:

- inspect a proposed value beside the highlighted source region;
- spot-check a risk-selected sample rather than retype the collection;
- confirm, correct, reject, defer, or supersede a candidate;
- confirm that a transcription is correct without thereby accepting its domain
  interpretation;
- review high-impact computations and unresolved conflicts; and
- approve a downstream output through a separate domain workflow.

The interface should explain why a value needs attention, how it was derived,
and where it will be used. Human review should be an explicit event, not an
inference from opening a page or leaving a machine value unchanged.

### Trust signals are orthogonal

The product must not compress confidence, agreement, validation, and review
into one misleading score.

| Signal | Meaning | What it does not prove |
| --- | --- | --- |
| Extractor confidence | A tool's estimate for its own output | Correctness or human review |
| Extractor agreement | Two or more methods emitted equivalent output | Truth; methods can share the same error |
| Deterministic validation | A rule, total, format, or cross-check passed | Correct source interpretation |
| Agent assessment | An identified agent accepted or recommended a candidate for a stated purpose | Human confirmation |
| Human confirmation | A person explicitly accepted or corrected a value for a stated purpose | Every downstream classification or calculation |

Review status and review actor are separate dimensions. At minimum, durable
review must distinguish an unreviewed machine candidate, a mechanically
validated candidate, an agent-assessed candidate, and human-confirmed evidence.
The underlying event also records its purpose, actor, time, notes, and any
replacement value.

### Review coverage is a product output

A provisional calculation or form export should summarize its evidence
coverage instead of presenting a binary illusion of completion. A useful
summary could report:

```text
Inputs used                         44
Human-confirmed                    18
Mechanically validated             17
Agent-assessed, not human-confirmed  6
Unreviewed                           3
Unresolved conflicts                 2
```

Each count remains navigable to the underlying values and source regions. A
domain policy may require human confirmation for particular fields or values
above a threshold while permitting sampled or machine-only treatment for
lower-risk inputs.

## Source-to-Form Review Interaction

The maintainer recalled a tax-workflow product that connected to an existing
enterprise document collection, mapped source documents into a company's
annual Swiss tax workflow, displayed extracted values beside named or numbered
government-form fields, and selected the corresponding PDF region with a
visible box. An accountant reviewed the proposed values rather than entering
all of them manually.

The exact company or product has not been identified reliably. Two current
Swiss products are close public matches:

- [Taxable.ch](https://taxable.ch/) describes Swiss fiduciary workflows in
  which extracted values link to the exact source document and official rule,
  and its review workspace highlights extractions with source citations.
- [crosstax](https://www.crosstax.online/en) displays proposed tax values with
  document, page, and confidence, opens the source, and does not take a value
  over until a person confirms it.

[iqtax](https://www.iqtax.ch/en) is another adjacent Swiss workflow: uploaded
documents are recognized and transferred into a tax return that remains ready
for review. [Dr. Tax](https://ringler.ch/) represents the established output
side of the market, covering Swiss cantons and forms for fiduciaries and
companies while announcing planned AI document-reading capabilities.

None of those public pages verifies the complete remembered combination of an
enterprise repository connector, company return, and exact red-box
interaction. The recollection therefore remains an unresolved lead.

The interaction itself is well established. [CCH Axcess Scan](https://www.wolterskluwer.com/en/solutions/cch-axcess/scan/features)
turns source documents into review-ready structured tax data, and the
[CCH K-1 verification interface](https://z001download.cchaxcess.com/PfxBrowserHelp/TAXHelp/Content/ImportExport/IE_Importing_K1_Engine_Verify.htm)
lets a reviewer select a line item, see a red box around the extracted value on
the source image, correct it, and then import it into the tax return.

Doc Evidence should adopt the interaction principle without importing a tax
domain into the core:

```text
source page and highlighted region
          <->
candidate value, provenance, status, and review action
          <->
semantic field and downstream uses
```

A tax domain pack can own jurisdiction, tax year, form, schedule, line, box,
calculation, and validation semantics. The generic core owns source identity,
page/region evidence, extraction identity, candidates, reviews, and lineage.
Every mapped field should support reverse traversal:

```text
form field
  -> versioned calculation or mapping
  -> source fact and review coverage
  -> candidate observation
  -> extractor run
  -> source content hash, page, and region
```

## Adjacent Product Landscape

No researched product combines all of Doc Evidence's intended boundaries.
The relevant landscape is a set of neighboring categories.

### Personal document management and electronic document management

- [Paperless-ngx](https://docs.paperless-ngx.com/usage/) consumes, OCRs,
  organizes, tags, and searches a personal document archive.
- [Docspell](https://docspell.org/docs/features/) provides OCR, full-text
  search, metadata analysis, background processing, and non-destructive
  retention of uploaded originals.
- [Mayan EDMS](https://docs.mayan-edms.com/chapters/features.html) adds mature
  document versioning, workflow, permissions, and enterprise lifecycle
  management.
- [DEVONthink](https://shop.devontechnologies.com/apps/devonthink/office) is a
  polished macOS document workplace with scanner integration, OCR, search,
  versioning, and document archiving.

These products optimize filing, retrieval, and lifecycle management. Doc
Evidence centers exact extractor-run identity, competing representations,
page/region provenance, and the path from candidate to reviewed fact. It may
later integrate with a document manager rather than replace one.

### Local and semantic document search

- [Recoll](https://www.recoll.org/) indexes heterogeneous local content and can
  open a PDF at the matching page. Its
  [OCR cache](https://recoll.org/usermanual/webhelp/docs/RCL.INDEXING.OCR.html)
  is content-hash based and survives source renames, a close technical analogue
  to Doc Evidence content identity.
- [Open Semantic Search](https://opensemanticsearch.org/) combines OCR,
  full-text and exploratory search, entity extraction, annotation, and
  structured research over many content types.

These systems are strong retrieval references. They do not generally retain
multiple extraction histories and purpose-specific evidence review as the main
product model.

### Research and investigative workbenches

- [Tropy](https://tropy.org/) is the closest researcher-centered UX reference:
  a local desktop application for organizing research photos, attaching
  metadata, annotating regions, and writing transcriptions and notes.
- [OCCRP Aleph](https://docs.aleph.occrp.org/about/) combines structured and
  unstructured investigative data, entity cross-referencing, network diagrams,
  timelines, documents, and leaks.
- [Hunchly](https://hunch.ly/) specializes in preserving and packaging web
  research for investigations.

Tropy suggests the source-centered local interaction. Aleph suggests later
entity, relationship, and chronology layers. Hunchly demonstrates that
evidence acquisition and preservation are separate specialties with stronger
claims than ordinary folder inventory.

### E-discovery and digital forensics

- [Everlaw](https://www.everlaw.com/ediscovery/),
  [RelativityOne](https://help.relativity.com/RelativityOne/index.htm), and
  [Nuix Workstation](https://www.nuix.com/solutions/workstation) process,
  search, review, code, redact, and produce large evidence collections for
  legal and investigative teams.
- [Autopsy](https://www.sleuthkit.org/autopsy/index.php) is a digital-forensics
  platform for device and filesystem evidence, with hash analysis and activity
  timelines.

These products establish the mature review concepts surrounding cases,
coding, privilege, legal hold, production, acquisition, and chain of custody.
Doc Evidence is currently a local single-user document workbench and must not
claim those guarantees by analogy.

### Tax workpapers, audit evidence, and intelligent document processing

- CCH Axcess Scan and its K-1 review workflow are direct references for
  source-region-to-field verification before tax import.
- [SurePrep](https://tax.thomsonreuters.com/en/sureprep) combines source
  collection, standardized workpaper organization, OCR verification, review
  sign-off, and export into established tax software. Its
  [GoFileRoom integration](https://www.thomsonreuters.com/en-us/help/gofileroom/firmflow/api-and-integrations/organize-tax-workpapers-with-sureprep)
  demonstrates processing source documents already assigned to an enterprise
  engagement rather than creating an unrelated filing system.
- Thomson Reuters'
  [Ready to Review](https://tax.thomsonreuters.com/en/products/ready-to-review/features)
  makes the emerging agentic direction explicit: agents gather documents,
  extract and verify values, identify missing material, map data into return
  fields, calculate, and prepare a filing for professional review.
- [DataSnipper](https://knowledge.datasnipper.com/guidance-for-documenting-your-audit-procedures-with-datasnipper)
  links workbook cells and audit procedures back to exact locations in source
  evidence so another reviewer can reperform the work.
- [Rossum](https://knowledge-base.rossum.ai/docs/interactive-bounding-boxes-in-rossum)
  demonstrates the generic intelligent-document-processing validation pattern:
  selecting an extracted field and its bounding box navigates between the
  structured value and source image.
- [Unstructured](https://unstructured.readthedocs.io/en/latest/core/partition.html),
  Docling, OCRmyPDF, Marker, and Tesseract are extraction ingredients rather
  than complete evidence products.

This is the closest commercial neighborhood to the intended
source-to-value-to-domain workflow. Doc Evidence differs by keeping the core
domain-neutral, local-first, multi-extractor, and explicit about review actor
and evidence status.

## Promising Use Cases

### Strong fit with the current foundation

- Private financial, tax, and cross-border record inventory.
- Estate, probate, inheritance, and family-record organization.
- Property, insurance, pension, benefits, and administrative dossiers.
- OCR and document-parser calibration by document class.
- Duplicate, variant, and archive-migration analysis before adopting a
  document-management system.
- Historical, genealogical, and small archival research collections.

These uses already benefit from read-only sources, hashing, extraction cache,
search, comparison, and local operation even before durable semantic review is
implemented.

### Strong fit after durable review and observations

- A reviewed source-fact ledger for tax, accounting, legal, or administrative
  work.
- A small-case evidence binder with issues, entities, chronology, conflicting
  records, and cited propositions.
- Risk-directed human review of financial statements, tax forms, contracts,
  claims, and compliance evidence.
- Form and report preparation through versioned jurisdiction/year domain packs.
- Evidence-backed agent workflows that assemble provisional outputs while
  preserving uncertainty and review coverage.
- Portable audit or reproducibility reports linking every accepted value to
  its source and derivation history.

### Later, materially larger product directions

- Multi-user professional review and approval.
- Connectors to enterprise document managers, client portals, accounting
  systems, and tax-preparation systems.
- Legal holds, privilege, redaction, Bates numbering, and production.
- Formal forensic acquisition and chain-of-custody guarantees.
- Hosted collaboration or controlled remote-model execution.

Those directions require distinct security, identity, retention, licensing,
deployment, and compliance decisions. They must not enter through an
apparently small UI feature.

## Product Boundaries and Claims

Doc Evidence is not yet:

- a scanner driver or mobile capture product;
- an inbox-centered replacement for Paperless-ngx or an enterprise DMS;
- a tax calculation engine in its generic core;
- a legal-hold, privilege-review, redaction, or production system;
- a forensically defensible acquisition and chain-of-custody platform;
- a multi-user records-management system; or
- a generic RAG or chat-with-your-folder product.

The word `evidence` currently means that source identity, derivation, location,
uncertainty, and review are explicit and inspectable. A claim of formal legal
or forensic defensibility would additionally require acquisition manifests,
append-only authenticated audit records, custody events, user identity and
permissions, retention controls, signed or otherwise verifiable exports, and
tested operational procedures.

## Product Priorities Suggested by the Landscape

1. Preserve the proposed macOS desktop proof as a distribution boundary, not a
   change in product ownership.
2. Implement durable review with actor, purpose, source region, correction,
   and portable export semantics.
3. Implement typed candidate observations and review queues that direct human
   attention by consequence and uncertainty.
4. Produce evidence-coverage summaries for provisional downstream work.
5. Define the first domain-pack contract around versioned fields,
   calculations, mappings, and reverse provenance without embedding tax rules
   in the generic core.
6. Add entity, chronology, and case organization only after the source-fact
   workflow is coherent.
7. Treat semantic/vector retrieval as a measured later need, not the product
   thesis.

The durable differentiator is not that Doc Evidence can OCR a document. It is
that automated work remains useful without becoming indistinguishable from
reviewed evidence.
