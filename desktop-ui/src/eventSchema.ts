import { z } from "zod";
import type { DesktopEvent } from "./events";
const text = z.string();
const nonnegative = z.number().int().nonnegative();
const strings = z.array(text);
const numbers = z.record(text, z.number().finite());
const kind = z.enum(["current", "future", "past", "reference"]);
const kinds = z.record(text, kind);
const implementation = z.enum(["unknown", "partial", "implemented", "not_implemented"]);
const source = z.object({ path: text, line: nonnegative, excerpt: text, sha256: text });
const place = z.object({ path: text, line: nonnegative, excerpt: text, criterion: text });
const item = z.object({
    id: text.min(1), source_key: text.optional(), title: text, criterion: text, area: text, included: z.boolean(), source,
    implementation_status: implementation, implementation_note: text.optional(),
    evidence: z.object({ path: text, line: nonnegative, note: text, excerpt: text.optional(), sha256: text.optional() }).nullable(),
    verification_status: z.enum(["unverified", "verified"]), verification_note: text,
    stale_evidence: z.boolean().optional(), stale_requirement: z.boolean().optional(),
    reviewed_documents: z.record(text, text).optional(), doc_marked_done: z.boolean().optional(),
    test_patterns: strings.optional(), doc_claim: z.literal("unbacked").nullable().optional(),
    duplicates: z.array(place).max(20).optional(),
    effective_status: z.enum(["unknown", "partial", "implemented", "not_implemented", "excluded"]).optional(),
}).passthrough();
const baseline = z.object({
    repository: text, documents: z.record(text, text), document_kinds: kinds.optional(),
    requirements: z.array(item).max(120), version: nonnegative.optional(),
}).passthrough();
// Draft inputs can be incomplete; e.g. a negative evidence line must survive recovery.
const recoveryBaseline = baseline.extend({ edit_base: baseline.nullable().optional(), requirements: z.array(item.extend({
    evidence: z.object({ path: text, line: z.number().finite().nullable(), note: text,
        excerpt: text.optional(), sha256: text.optional() }).nullable(),
})).max(120) });
const report = z.object({
    repository: text, version: nonnegative, at: text, head: text, total: nonnegative,
    stale_documents: strings, counts: numbers, items: z.array(item), limitations: text,
    document_kinds: kinds.optional(), stale_context_documents: strings.optional(),
    doc_claims_unbacked: nonnegative.optional(), test_pattern_hints: z.record(text, strings).optional(),
}).passthrough();
const changeItem = z.object({ id: text, title: text });
const changes = { gained: z.array(changeItem), regressed: z.array(changeItem), excluded: z.array(changeItem),
    reincluded: z.array(changeItem), added: z.array(changeItem), removed: z.array(changeItem) };
const history = {
    snapshots: z.array(z.object({ at: text, version: nonnegative, head: text, total: nonnegative, counts: numbers,
        changes: numbers.nullable().optional(), complete_delta: z.number().nullable().optional() })),
    since_save: z.object({ since: text, version: nonnegative, complete_delta: z.number(), counts: numbers, ...changes }).nullable(),
};
const fieldError = z.object({ id: text, field: text, message: text });
const progressMeta = { requested_path: text, request_id: text, request_done: z.boolean().optional() };
const meta = { requested_path: text.optional(), request_id: text.optional(), request_done: z.boolean().optional() };
const document = z.object({ path: text, tracked: z.boolean(), bytes: nonnegative });
const candidate = z.object({ path: text, line: nonnegative, excerpt: text });
const testLink = z.object({ patterns: strings, matched: nonnegative, passed: nonnegative, failed: nonnegative,
    skipped: nonnegative, failing: strings, no_match: z.boolean(), code_newer: z.boolean().optional() });
const issue = z.object({ path: text, line: nonnegative, target: text, kind: z.enum(["link", "path", "document"]),
    confidence: z.enum(["high", "low"]).optional(), message: text });
const group = z.object({ name: text, required: strings.optional(), evidence: text.optional() }).passthrough();
const decision = z.object({ rule_id: text, status: text, reason: text, severity: text.optional(), trigger_files: strings,
    unsatisfied_groups: z.array(group), satisfied_groups: z.array(group) }).passthrough();
const violation = z.object({ rule_id: text, severity: text, confidence: text, message: text, checklist: strings,
    missing_docs_explanation: text, changed_contract_summary: text, docs_update_draft: text, false_positive_note: text }).passthrough();
const scan = z.object({ repository: text, base: text, at: text, changed_file_count: nonnegative, policy: text,
    files: z.array(z.object({ path: text, patch: text, status: text })),
    result: z.object({ result: text, rule_decisions: z.array(decision), violations: z.array(violation).optional(),
        scan_metrics: z.object({ analysis_notes: z.array(z.object({ path: text, method: text, reason: text.optional() }).passthrough()).optional() }).passthrough().optional(),
    }).passthrough() });
const schema = z.discriminatedUnion("type", [
    z.object({ type: z.literal("progressDocs"), ...progressMeta, documents: z.array(document), omitted: nonnegative, repository: text.optional(), baseline: baseline.nullable().optional(),
        recovery: recoveryBaseline.nullable().optional().catch(null), recovery_warning: text.optional(),
        recovery_key: text.optional(), recovery_revision: text.optional(), recovery_options: z.array(z.object({ key: text, updated_at: text, revision: text.optional(), bytes: nonnegative.optional(), active: z.boolean().optional() })).optional() }),
    z.object({ type: z.literal("progressDraftCached"), ...progressMeta }),
    z.object({ type: z.literal("progressDraftDiscarded"), ...progressMeta }),
    z.object({ type: z.literal("progressDraftError"), ...progressMeta, message: text }),
    z.object({ type: z.literal("progressPreview"), ...progressMeta, repository: text.optional(), truncated: z.boolean().optional(),
        documents: z.record(text, text), document_kinds: kinds.optional(), requirements: z.array(item).max(120) }),
    z.object({ type: z.literal("progressSaved"), ...progressMeta, baseline, warning: text.optional() }),
    z.object({ type: z.literal("progressReport"), ...progressMeta, report }),
    z.object({ type: z.literal("progressHistory"), ...progressMeta, ...history }),
    z.object({ type: z.literal("progressTests"), ...progressMeta, format: text, file: text, modified: text,
        total: nonnegative, remembered: z.boolean().optional(), items: z.record(text, testLink) }),
    z.object({ type: z.literal("progressTestsCancelled"), ...progressMeta }),
    z.object({ type: z.literal("progressLinks"), ...progressMeta, documents: strings, checked: nonnegative,
        issues: z.array(issue), truncated: z.boolean(), limitations: text }),
    z.object({ type: z.literal("progressEvidence"), ...progressMeta, id: text, candidates: z.array(candidate) }),
    z.object({ type: z.literal("progressDraftExported"), ...progressMeta, file: text }),
    z.object({ type: z.literal("progressDraftExportCancelled"), ...progressMeta }),
    z.object({ type: z.literal("progressLatestUsed"), ...progressMeta, baseline, warning: text.optional() }),
    z.object({ type: z.literal("progressExported"), ...progressMeta, file: text }),
    z.object({ type: z.literal("progressError"), ...progressMeta, message: text, errors: z.array(fieldError).optional(), current_baseline: baseline.optional() }),
    z.object({ type: z.literal("ready"), ...meta, repository: text, base: text, installed: z.record(text, text) }),
    z.object({ type: z.literal("repository"), ...meta, path: text }),
    z.object({ type: z.literal("scanning"), ...meta }),
    z.object({ type: z.literal("scanned"), ...meta, scan }),
    z.object({ type: z.literal("policyMissing"), ...meta, repository: text }),
    z.object({ type: z.literal("policyPreview"), ...meta, repository: text, exists: z.boolean(), preset: text, presets: strings,
        recommendations: z.object({ presets: strings, frameworks: strings, docs_paths: strings }), policy: text }),
    z.object({ type: z.literal("policyCreated"), ...meta, path: text, repository: text.optional(), preset: text.optional() }),
    z.object({ type: z.literal("scanImpact"), ...meta, scan_at: text, version: nonnegative,
        items: z.array(z.object({ id: text, title: text, path: text, line: nonnegative.optional(), change: text, invalidated: z.boolean() })),
        documents: z.array(z.object({ path: text, invalidated: z.boolean(), kind: kind.optional() })) }),
    z.object({ type: z.literal("preview"), ...meta, prompt: text }),
    z.object({ type: z.literal("reviewing"), ...meta }),
    z.object({ type: z.literal("reviewed"), ...meta, review: z.object({ provider: text, verdict: text, summary: text,
            findings: z.array(z.object({ rule_id: text, reason: text, suggestion: text })), limitations: strings }) }),
    z.object({ type: z.literal("error"), ...meta, message: text }),
    z.object({ type: z.literal("reviewError"), ...meta, message: text }),
    z.object({ type: z.literal("saved"), ...meta, path: text }),
]) satisfies z.ZodType<DesktopEvent>;
/** Validate wire data before React; failures retain only checked request context. */
export function decodeDesktopEvent(raw: string): DesktopEvent {
    let value: unknown;
    try {
        value = JSON.parse(raw);
    }
    catch {
        return { type: "error", message: "앱 응답을 읽지 못했습니다." };
    }
    const parsed = schema.safeParse(value);
    if (parsed.success) {
        if (parsed.data.type === "progressDocs" && value && typeof value === "object" && "recovery" in value
            && value.recovery && parsed.data.recovery === null)
            return { ...parsed.data, recovery_warning: "보관된 초안의 형식이 올바르지 않습니다. 확정된 기준은 유지했습니다." };
        return parsed.data;
    }
    if (value && typeof value === "object" && "type" in value && typeof value.type === "string" && value.type.startsWith("progress")
        && "requested_path" in value && typeof value.requested_path === "string"
        && "request_id" in value && typeof value.request_id === "string") {
        return { type: value.type === 'progressDraftCached' || value.type === 'progressDraftError' ? 'progressDraftError' : 'progressError',
            requested_path: value.requested_path, request_id: value.request_id,
            request_done: true, message: "현황 응답 형식이 올바르지 않습니다. 다시 시도해 주세요." };
    }
    return { type: "error", message: "앱 응답 형식이 올바르지 않습니다. 다시 시도해 주세요." };
}
